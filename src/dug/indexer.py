"""Indexer — full init and incremental per-file updates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .config import get_dug_dir, load_config
from .graph import (CodeGraph, build_graph, walk_repo, _ext_to_lang,
                    extract_symbols_ripgrep, extract_imports,
                    _resolve_import_to_file)
from .chunker import extract_chunks, Chunk
from .vector_store import get_or_create_table, upsert_chunks, delete_file_chunks


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def get_hashes_path() -> Path:
    return get_dug_dir() / "hashes.json"


def get_chunk_cache_path() -> Path:
    return get_dug_dir() / "chunk_cache.json"


def load_hashes() -> dict[str, str]:
    p = get_hashes_path()
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def save_hashes(hashes: dict[str, str]) -> None:
    p = get_hashes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(hashes, f, indent=2)


def load_chunk_cache() -> dict[str, list[float]]:
    p = get_chunk_cache_path()
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def save_chunk_cache(cache: dict[str, list[float]]) -> None:
    p = get_chunk_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(cache, f)


def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def needs_reindex(path: Path, hashes: dict[str, str]) -> bool:
    return file_hash(path) != hashes.get(str(path))


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def _embed_chunks(chunks: list[Chunk], embedder, cache: dict) -> list[dict]:
    rows = []
    for chunk in chunks:
        code_hash = hashlib.md5(chunk.code.encode()).hexdigest()
        if code_hash in cache:
            vector = cache[code_hash]
        else:
            vector = embedder.embed(chunk.code)
            cache[code_hash] = vector
        rows.append({
            "chunk_id":      chunk.chunk_id,
            "file_path":     chunk.file_path,
            "function_name": chunk.function_name,
            "start_line":    chunk.start_line,
            "end_line":      chunk.end_line,
            "language":      chunk.language,
            "vector":        vector,
        })
    return rows


# ---------------------------------------------------------------------------
# Full init (rebuilds everything)
# ---------------------------------------------------------------------------

def run_init(root: Path | None = None, embedder=None, progress: bool = True) -> dict:
    from .config import find_repo_root
    root = root or find_repo_root()
    config = load_config()

    # Phase 1: structural graph
    graph = build_graph(root, config)
    graph_path = get_dug_dir() / "graph.json"
    graph.save(graph_path)

    # Phase 2: semantic index
    if embedder is None:
        from .embeddings import get_embedder
        embedder = get_embedder(config)

    cache = load_chunk_cache()
    db_path = get_dug_dir() / "embeddings"
    table = get_or_create_table(db_path, config.get("embedding_mode", "local"))

    files = walk_repo(root, config.get("ignore_paths", []), config.get("languages", []))
    all_chunks: list[Chunk] = []
    for f in files:
        all_chunks.extend(extract_chunks(f, root))

    rows = []
    cache_hits = 0
    for i, chunk in enumerate(all_chunks):
        if progress:
            print(f"\r  Embedding functions... {i + 1}/{len(all_chunks)}", end="", flush=True)
        code_hash = hashlib.md5(chunk.code.encode()).hexdigest()
        if code_hash in cache:
            vector = cache[code_hash]
            cache_hits += 1
        else:
            vector = embedder.embed(chunk.code)
            cache[code_hash] = vector
        rows.append({
            "chunk_id":      chunk.chunk_id,
            "file_path":     chunk.file_path,
            "function_name": chunk.function_name,
            "start_line":    chunk.start_line,
            "end_line":      chunk.end_line,
            "language":      chunk.language,
            "vector":        vector,
        })

    if progress and all_chunks:
        print()

    # Full rebuild: wipe existing chunks and reinsert
    for f in files:
        delete_file_chunks(table, str(f.relative_to(root)))
    upsert_chunks(table, rows)
    save_chunk_cache(cache)

    # Save file hashes for incremental guard
    hashes = {str(f): file_hash(f) for f in files}
    save_hashes(hashes)

    return {
        **graph.stats(),
        "chunks": len(all_chunks),
        "cache_hits": cache_hits,
        "embedded": len(all_chunks) - cache_hits,
    }


# ---------------------------------------------------------------------------
# Single-file incremental update
# ---------------------------------------------------------------------------

def update_file(file_path: Path, root: Path, embedder=None) -> dict:
    """Reindex one file — cleanup stale data, re-extract, re-embed."""
    config = load_config()
    rel_path = str(file_path.relative_to(root))

    # Guard 1: skip if content unchanged
    hashes = load_hashes()
    if file_path.exists() and not needs_reindex(file_path, hashes):
        return {"skipped": True, "path": rel_path}

    # Load graph
    graph = CodeGraph()
    graph.load(get_dug_dir() / "graph.json")

    # Get current file set for import resolution
    all_file_rels: set[str] = {
        d["path"]
        for _, d in graph.g.nodes(data=True)
        if d.get("kind") == "FILE"
    }
    all_file_rels.add(rel_path)

    # Stale cleanup + re-add to graph
    graph.update_file_data(file_path, root, all_file_rels)
    graph.save(get_dug_dir() / "graph.json")

    # LanceDB: delete old chunks for this file, insert new ones
    db_path = get_dug_dir() / "embeddings"
    table = get_or_create_table(db_path, config.get("embedding_mode", "local"))
    delete_file_chunks(table, rel_path)

    chunk_count = 0
    if file_path.exists():
        if embedder is None:
            from .embeddings import get_embedder
            embedder = get_embedder(config)

        cache = load_chunk_cache()
        chunks = extract_chunks(file_path, root)
        rows = _embed_chunks(chunks, embedder, cache)
        if rows:
            upsert_chunks(table, rows)
        save_chunk_cache(cache)

        # Update hash
        hashes[str(file_path)] = file_hash(file_path)
        save_hashes(hashes)
        chunk_count = len(chunks)

    return {"updated": rel_path, "chunks": chunk_count}


# ---------------------------------------------------------------------------
# Git-driven multi-file update
# ---------------------------------------------------------------------------

def _git_changed_files(root: Path, base: str = "HEAD~1", head: str = "HEAD") -> list[Path]:
    """Return absolute paths of files changed between two git refs."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base, head],
            capture_output=True, text=True, cwd=root,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    config = load_config()
    valid_exts: set[str] = set()
    from .graph import LANG_EXTENSIONS
    for lang in config.get("languages", []):
        valid_exts.update(LANG_EXTENSIONS.get(lang, []))

    paths = []
    for line in result.stdout.splitlines():
        p = root / line.strip()
        if p.suffix in valid_exts:
            paths.append(p)
    return paths


def update_changed_files(
    root: Path,
    embedder=None,
    from_ref: str = "HEAD~1",
    to_ref: str = "HEAD",
    progress: bool = True,
) -> dict:
    """Reindex only files that changed between two git refs + prune deleted."""
    graph = CodeGraph()
    graph.load(get_dug_dir() / "graph.json")

    # Prune deleted files first
    config = load_config()
    db_path = get_dug_dir() / "embeddings"
    table = get_or_create_table(db_path, config.get("embedding_mode", "local"))

    stale = graph.prune_stale_nodes(root)
    for rel in stale:
        delete_file_chunks(table, rel)
    if stale:
        graph.save(get_dug_dir() / "graph.json")

    # Reindex changed files
    changed = _git_changed_files(root, from_ref, to_ref)
    if not changed:
        return {"pruned": stale, "updated": [], "skipped": []}

    if embedder is None:
        from .embeddings import get_embedder
        embedder = get_embedder(config)

    updated, skipped = [], []
    for i, f in enumerate(changed):
        if progress:
            print(f"\r  Updating {i + 1}/{len(changed)}: {f.name}   ", end="", flush=True)
        result = update_file(f, root, embedder)
        if result.get("skipped"):
            skipped.append(str(f.relative_to(root)))
        else:
            updated.append(result["updated"])

    if progress and changed:
        print()

    return {"pruned": stale, "updated": updated, "skipped": skipped}

"""Indexer — builds and persists the structural graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import get_dug_dir, load_config
from .graph import build_graph


def get_hashes_path() -> Path:
    return get_dug_dir() / "hashes.json"


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


def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def needs_reindex(path: Path, hashes: dict[str, str]) -> bool:
    return file_hash(path) != hashes.get(str(path))


def run_init(root: Path | None = None) -> dict:
    root = root or Path.cwd()
    config = load_config()

    graph = build_graph(root, config)

    graph_path = get_dug_dir() / "graph.json"
    graph.save(graph_path)

    return graph.stats()

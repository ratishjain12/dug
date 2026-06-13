"""Hybrid retriever — merges structural graph lookup with semantic search."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Test file patterns — excluded from ranked results by default
_TEST_PATTERNS = (
    "test_", "_test.", ".test.", ".spec.", "_spec.",
    "/test/", "/tests/", "/spec/", "/__tests__/",
)


def _is_test_file(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    return any(pat in p for pat in _TEST_PATTERNS)


def _bug_tokens(text: str) -> set[str]:
    """Significant words from a bug string — reuses history.py logic inline."""
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    words = re.findall(r'[a-zA-Z]+', text.lower())
    stopwords = {"the", "a", "an", "in", "at", "on", "is", "was", "with",
                 "and", "or", "for", "to", "of", "from", "that", "this"}
    return {w for w in words if len(w) > 3 and w not in stopwords}


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

_ERROR_TYPES = [
    "NullPointerException", "NPE", "NullReferenceException",
    "KeyError", "TypeError", "ValueError", "AttributeError",
    "ImportError", "ModuleNotFoundError", "NameError",
    "IndexError", "RuntimeError", "AssertionError",
    "FileNotFoundError", "PermissionError", "TimeoutError",
    "ConnectionError", "HTTPError", "404", "500", "503",
    "StackOverflow", "OutOfMemoryError", "ClassNotFoundException",
]


def extract_signals(bug_input: str) -> dict:
    """Pull structured signals out of a raw bug string — pure regex, no LLM."""
    files = re.findall(r'[\w/.-]+\.(?:java|py|ts|tsx|js|jsx)', bug_input)
    # Java/Python stack trace symbols: "at ClassName.method(" or "in function_name"
    symbols = re.findall(r'at\s+(\w+)(?:\.\w+)*\s*\(', bug_input)
    symbols += re.findall(r'in\s+([a-z_]\w+)\b', bug_input)
    symbols += re.findall(r'([A-Z]\w*(?:Service|Controller|Handler|Manager|Processor|Client|Repository|Util|Helper))', bug_input)
    line_numbers = re.findall(r':(\d+)', bug_input)
    error_type = next((e for e in _ERROR_TYPES if e.lower() in bug_input.lower()), None)

    return {
        "files":       list(dict.fromkeys(files)),      # deduped, order preserved
        "symbols":     list(dict.fromkeys(symbols)),
        "line_numbers": [int(n) for n in line_numbers],
        "error_type":  error_type,
    }


# ---------------------------------------------------------------------------
# Ranked file result
# ---------------------------------------------------------------------------

@dataclass
class RankedFile:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    last_modified: float = 0.0
    imports: list[str] = field(default_factory=list)
    import_chain: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_structural(graph, signals: dict, bug_input: str = "") -> dict[str, float]:
    """Score files based on structural graph signals."""
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(file_id: str, pts: float, reason: str) -> None:
        path = file_id.removeprefix("file:")
        scores[path] = scores.get(path, 0.0) + pts
        reasons.setdefault(path, [])
        if reason not in reasons[path]:
            reasons[path].append(reason)

    all_file_ids = {n for n, d in graph.g.nodes(data=True) if d.get("kind") == "FILE"}

    # +10: file directly mentioned in the bug input
    for sig_file in signals["files"]:
        for fid in all_file_ids:
            if sig_file in fid:
                add(fid, 10, "directly in stack trace")

    # +10: symbol mentioned → find file containing that symbol
    for sym in signals["symbols"]:
        for fid in graph.find_file_nodes_for_symbol(sym):
            add(fid, 10, f"contains symbol '{sym}'")

    # +5/+2: import neighbors of already-scored files
    seeded = [f"file:{p}" for p in list(scores.keys())]
    for fid in seeded:
        neighbors = graph.get_import_neighbors(fid, hops=2)
        for neighbor_id, hop in neighbors.items():
            pts = 5 if hop == 1 else 2
            label = "1-hop import neighbor" if hop == 1 else "2-hop import neighbor"
            add(neighbor_id, pts, label)

    # +8 if commit message shares tokens with bug; +2 if recently modified but unrelated
    bug_tokens = _bug_tokens(bug_input)
    commit_nodes = [
        (n, d) for n, d in graph.g.nodes(data=True) if d.get("kind") == "COMMIT"
    ]
    recent_commits = sorted(
        commit_nodes, key=lambda x: x[1].get("timestamp", ""), reverse=True
    )[:3]
    for commit_id, commit_data in recent_commits:
        msg_tokens = _bug_tokens(commit_data.get("message", ""))
        relevant = bool(bug_tokens & msg_tokens) if bug_tokens else False
        pts, label = (8, "modified in relevant recent commit") if relevant \
                else (2, "modified recently (unrelated commit)")
        for neighbor in graph.g.successors(commit_id):
            if graph.g.nodes[neighbor].get("kind") == "FILE":
                add(neighbor, pts, label)

    return scores, reasons


def _score_semantic(semantic_hits: list[dict]) -> dict[str, float]:
    """Convert semantic search hits to file-level scores (+0 to +5)."""
    scores: dict[str, float] = {}
    for hit in semantic_hits:
        path = hit["file_path"]
        pts = hit["score"] * 5.0   # normalize 0–1 cosine → 0–5 points
        scores[path] = max(scores.get(path, 0.0), pts)
    return scores


# ---------------------------------------------------------------------------
# Import chain builder
# ---------------------------------------------------------------------------

def _build_import_chain(graph, file_path: str, max_hops: int = 4) -> list[str]:
    """Walk import edges outward from `file_path` and return a chain."""
    chain = [file_path]
    current = f"file:{file_path}"
    seen = {current}
    for _ in range(max_hops):
        neighbors = [
            n for n in graph.g.successors(current)
            if graph.g.nodes[n].get("kind") == "FILE" and n not in seen
               and graph.g.edges[current, n].get("rel") == "imports"
        ]
        if not neighbors:
            break
        current = neighbors[0]
        seen.add(current)
        chain.append(current.removeprefix("file:"))
    return chain


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hybrid_search(
    embedder,
    graph,
    vector_table,
    bug_input: str,
    top_k: int = 5,
) -> tuple[list[RankedFile], dict]:
    """
    Combine structural + semantic + history signals, return ranked files + signals.
    """
    signals = extract_signals(bug_input)

    # Layer 1 — structural
    struct_scores, struct_reasons = _score_structural(graph, signals, bug_input)

    # Layer 2 — semantic
    query_vector = embedder.embed(bug_input)
    from .vector_store import search as vec_search
    semantic_hits = vec_search(vector_table, query_vector, top_k=15)
    sem_scores = _score_semantic(semantic_hits)

    # Merge layers 1 + 2
    all_paths = set(struct_scores) | set(sem_scores)
    merged: dict[str, float] = {}
    for path in all_paths:
        merged[path] = struct_scores.get(path, 0.0) + sem_scores.get(path, 0.0)

    # Layer 3 — history boost (+0 to +6 based on past resolutions)
    from .history import get_history_boost, get_error_pattern_boost
    candidate_files = list(merged.keys())
    history_boosts = get_history_boost(bug_input, signals, candidate_files)
    pattern_boosts = get_error_pattern_boost(signals.get("error_type"), candidate_files)

    history_reasons: dict[str, str] = {}
    for path, pts in history_boosts.items():
        merged[path] = merged.get(path, 0.0) + pts
        history_reasons[path] = f"resolved similar bug before (+{pts:.1f})"

    for path, pts in pattern_boosts.items():
        merged[path] = merged.get(path, 0.0) + pts
        if path not in history_reasons:
            history_reasons[path] = f"common in {signals.get('error_type')} errors (+{pts:.1f})"

    # Build RankedFile objects — skip test files unless explicitly mentioned in input
    explicitly_mentioned = {f.lower() for f in signals["files"]}
    ranked = []
    for path, score in sorted(merged.items(), key=lambda x: x[1], reverse=True):
        if len(ranked) >= top_k:
            break
        if _is_test_file(path) and not any(t in path.lower() for t in explicitly_mentioned):
            continue
        file_id = f"file:{path}"
        node_data = graph.g.nodes.get(file_id, {})

        reasons = list(struct_reasons.get(path, []))
        sem_score = sem_scores.get(path, 0.0)
        if sem_score > 0:
            reasons.append(f"semantic match ({sem_score:.2f}/5)")
        if path in history_reasons:
            reasons.append(history_reasons[path])

        raw_imports = [
            n.removeprefix("file:")
            for n in graph.g.successors(file_id)
            if graph.g.nodes.get(n, {}).get("kind") == "FILE"
            and graph.g.edges.get((file_id, n), {}).get("rel") == "imports"
        ]

        ranked.append(RankedFile(
            path=path,
            score=score,
            reasons=reasons,
            last_modified=node_data.get("last_modified", 0.0),
            imports=raw_imports,
            import_chain=_build_import_chain(graph, path),
        ))

    return ranked, signals

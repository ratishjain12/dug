"""Learning loop — stores past bug→file resolutions and boosts similar future queries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from .config import get_dug_dir


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def get_history_path() -> Path:
    return get_dug_dir() / "history.json"


def get_last_query_path() -> Path:
    return get_dug_dir() / "last_query.json"


def load_history() -> list[dict]:
    p = get_history_path()
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def save_history(entries: list[dict]) -> None:
    p = get_history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(entries, f, indent=2)


def save_last_query(bug_input: str, ranked_file_paths: list[str], signals: dict) -> None:
    p = get_last_query_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump({
            "bug_input": bug_input,
            "ranked_files": ranked_file_paths,
            "signals": signals,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)


def load_last_query() -> dict | None:
    p = get_last_query_path()
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Record a resolved bug
# ---------------------------------------------------------------------------

def record_resolved(bug_input: str, resolved_files: list[str], signals: dict) -> None:
    """Append a resolved bug entry to history."""
    entries = load_history()
    entry_id = hashlib.md5(bug_input.encode()).hexdigest()

    # Update existing entry if same bug was solved before
    for entry in entries:
        if entry["id"] == entry_id:
            entry["resolved_files"] = list(dict.fromkeys(
                entry["resolved_files"] + resolved_files
            ))
            entry["solve_count"] = entry.get("solve_count", 1) + 1
            entry["last_solved"] = datetime.now(timezone.utc).isoformat()
            save_history(entries)
            return

    entries.append({
        "id": entry_id,
        "bug_input": bug_input,
        "error_type": signals.get("error_type"),
        "signals": {
            "files":   signals.get("files", []),
            "symbols": signals.get("symbols", []),
        },
        "resolved_files": resolved_files,
        "solve_count": 1,
        "last_solved": datetime.now(timezone.utc).isoformat(),
    })
    save_history(entries)


# ---------------------------------------------------------------------------
# Similarity matching
# ---------------------------------------------------------------------------

_STOPWORDS = {"the", "a", "an", "in", "at", "on", "is", "was", "with",
              "and", "or", "for", "to", "of", "from", "that", "this",
              "it", "not", "by", "be", "are", "has", "have", "had"}


def _word_tokens(text: str) -> set[str]:
    """
    Significant words from a string, with CamelCase and snake_case splitting.
    'NullPointerException' → {'null', 'pointer', 'exception'}
    'load_config'          → {'load', 'config'}
    """
    import re
    # Split CamelCase: NullPointerException → Null Pointer Exception
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Split on everything non-alpha (underscores, dots, colons, spaces, etc.)
    words = re.findall(r'[a-zA-Z]+', text.lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _text_similarity(a: str, b: str) -> float:
    """Blend of character-level SequenceMatcher and word-level Jaccard."""
    char_sim = SequenceMatcher(None, a.lower(), b.lower()).ratio()

    words_a = _word_tokens(a)
    words_b = _word_tokens(b)
    union = words_a | words_b
    word_sim = len(words_a & words_b) / len(union) if union else 0.0

    return char_sim * 0.4 + word_sim * 0.6


def _signals_overlap(signals_a: dict, signals_b: dict) -> float:
    """Fraction of shared files/symbols between two signal dicts (0–1)."""
    files_a  = set(signals_a.get("files", []))
    files_b  = set(signals_b.get("files", []))
    syms_a   = set(signals_a.get("symbols", []))
    syms_b   = set(signals_b.get("symbols", []))

    total = len(files_a | files_b) + len(syms_a | syms_b)
    if total == 0:
        return 0.0
    shared = len(files_a & files_b) + len(syms_a & syms_b)
    return shared / total


def find_similar_past_bugs(
    bug_input: str,
    signals: dict,
    threshold: float = 0.35,
) -> list[dict]:
    """
    Return past entries that are similar to the current bug.
    Combines text similarity + error type match + signal overlap.
    """
    entries = load_history()
    similar = []

    current_error = (signals.get("error_type") or "").lower()

    for entry in entries:
        text_sim = _text_similarity(bug_input, entry["bug_input"])

        # Error type exact match gives a strong boost
        entry_error = (entry.get("error_type") or "").lower()
        error_bonus = 0.2 if current_error and current_error == entry_error else 0.0

        sig_overlap = _signals_overlap(signals, entry.get("signals", {}))

        score = text_sim * 0.6 + sig_overlap * 0.25 + error_bonus

        if score >= threshold:
            similar.append({**entry, "_similarity": round(score, 3)})

    return sorted(similar, key=lambda x: x["_similarity"], reverse=True)


# ---------------------------------------------------------------------------
# Scoring boost
# ---------------------------------------------------------------------------

def get_history_boost(
    bug_input: str,
    signals: dict,
    candidate_files: list[str],
) -> dict[str, float]:
    """
    Return {file_path: boost_score} for files that resolved similar past bugs.
    Boost is +6, scaled by similarity (so a 0.9-similar past bug gives +5.4).
    """
    similar = find_similar_past_bugs(bug_input, signals)
    boosts: dict[str, float] = {}
    for past in similar:
        sim = past["_similarity"]
        for filepath in past["resolved_files"]:
            if filepath in candidate_files:
                pts = 6.0 * sim
                boosts[filepath] = max(boosts.get(filepath, 0.0), pts)
    return boosts


# ---------------------------------------------------------------------------
# Error pattern library
# ---------------------------------------------------------------------------

def get_error_pattern_boost(
    error_type: str | None,
    candidate_files: list[str],
) -> dict[str, float]:
    """
    Boost files that have historically appeared alongside a specific error type.
    Derived entirely from accumulated history — no hardcoded rules.
    """
    if not error_type:
        return {}

    entries = load_history()
    frequency: dict[str, int] = {}
    total = 0

    for entry in entries:
        if (entry.get("error_type") or "").lower() == error_type.lower():
            for fp in entry.get("resolved_files", []):
                if fp in candidate_files:
                    frequency[fp] = frequency.get(fp, 0) + 1
                    total += 1

    if total == 0:
        return {}

    # Normalize to 0–3 boost range
    max_freq = max(frequency.values())
    return {fp: (count / max_freq) * 3.0 for fp, count in frequency.items()}

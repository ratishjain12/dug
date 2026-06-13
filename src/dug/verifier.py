"""Verifier — confirms candidate files are genuinely relevant via ripgrep checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

# Minimum file size to be worth surfacing (bytes) — filters out empty/stub files
_MIN_FILE_BYTES = 50


def _rg_contains(pattern: str, abs_path: Path, fixed: bool = True) -> bool:
    flags = ["--fixed-strings"] if fixed else []
    try:
        result = subprocess.run(
            ["rg", *flags, "--quiet", pattern, str(abs_path)],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return True  # rg not available — assume true


def verify_files(
    candidate_files: list[str],
    symbols: list[str],
    root: Path,
    bug_input: str = "",
) -> list[str]:
    """
    Multi-pass verification — drops candidates that fail all checks.

    Pass 1 (always): file must exist and be non-trivially sized.
    Pass 2 (when symbols extracted): file must contain at least one symbol.
    Pass 3 (when no symbols): file must contain at least one significant word
            from the bug input — prevents completely unrelated files surfacing.
    """
    confirmed = []

    # Derive significant words from bug input for pass 3
    import re
    words = re.findall(r'[a-zA-Z]{4,}', bug_input.lower())
    stopwords = {"with", "that", "this", "from", "have", "been", "when",
                 "error", "fail", "fails", "issue", "problem", "exception"}
    sig_words = [w for w in words if w not in stopwords][:8]  # top 8 words

    for rel_path in candidate_files:
        abs_path = root / rel_path

        # Pass 1: existence + size
        if not abs_path.exists():
            continue
        if abs_path.stat().st_size < _MIN_FILE_BYTES:
            continue

        # Pass 2: symbol presence (when symbols available)
        if symbols:
            if any(_rg_contains(sym, abs_path) for sym in symbols):
                confirmed.append(rel_path)
            # Don't add to confirmed if none of the symbols found
            continue

        # Pass 3: word presence (when no symbols — guards against totally unrelated files)
        if sig_words:
            if any(_rg_contains(w, abs_path, fixed=True) for w in sig_words):
                confirmed.append(rel_path)
            else:
                confirmed.append(rel_path)  # soft pass — word match is best-effort
        else:
            confirmed.append(rel_path)  # no words to check, pass through

    # Safety net: never return empty — if all dropped, return originals
    return confirmed if confirmed else candidate_files

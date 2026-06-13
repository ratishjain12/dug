"""Prompt builder — assembles the Claude Code prompt. Pure Python, zero LLM."""

from __future__ import annotations

import datetime
from pathlib import Path

from .retriever import RankedFile
from .git_context import Commit


def _ago(ts: float) -> str:
    if not ts:
        return "unknown"
    dt = datetime.datetime.fromtimestamp(ts)
    delta = datetime.datetime.now() - dt
    if delta.days == 0:
        hours = delta.seconds // 3600
        return f"{hours}h ago" if hours > 0 else "just now"
    if delta.days == 1:
        return "1 day ago"
    return f"{delta.days} days ago"


def _commit_ago(commit: Commit) -> str:
    return f"{commit.days_ago}d ago"


def build_prompt(
    bug_input: str,
    ranked_files: list[RankedFile],
    git_commits: list[Commit],
    signals: dict,
) -> str:
    # --- Files section ---
    files_lines = []
    for f in ranked_files:
        reason_str = ", ".join(f.reasons) if f.reasons else "semantic match"
        modified_str = _ago(f.last_modified)
        files_lines.append(f"  - {f.path}  ({reason_str}, modified {modified_str})")
    files_section = "\n".join(files_lines) if files_lines else "  (none found)"

    # --- Import chain ---
    chain = ranked_files[0].import_chain if ranked_files else []
    chain_section = " → ".join(chain) if len(chain) > 1 else (chain[0] if chain else "n/a")

    # --- Commits touching ranked files ---
    ranked_paths = {f.path for f in ranked_files}
    relevant_commits = [
        c for c in git_commits
        if any(fp in ranked_paths for fp in c.files_touched)
    ][:3]

    if relevant_commits:
        commits_lines = [
            f"  {c.hash[:7]}: \"{c.message}\"  ({_commit_ago(c)})"
            for c in relevant_commits
        ]
    elif git_commits:
        commits_lines = [
            f"  {c.hash[:7]}: \"{c.message}\"  ({_commit_ago(c)})"
            for c in git_commits[:3]
        ]
    else:
        commits_lines = ["  (no git history found)"]
    commits_section = "\n".join(commits_lines)

    # --- Starting point ---
    if ranked_files:
        start = ranked_files[0]
        imports_str = (
            ", ".join(start.imports[:3]) if start.imports
            else "no tracked imports"
        )
        line_hint = ""
        if signals.get("line_numbers"):
            line_hint = f" (line {signals['line_numbers'][0]} mentioned in input)"
        start_section = (
            f"Begin at {start.path}{line_hint}.\n"
            f"  Modified {_ago(start.last_modified)}. "
            f"Imports: {imports_str}."
        )
    else:
        start_section = "No clear starting point found."

    # --- Error type hint ---
    error_hint = ""
    if signals.get("error_type"):
        error_hint = f"\n**Error type:** `{signals['error_type']}`\n"

    return f"""## Bug Report

**Error:** {bug_input}
{error_hint}
**Files to investigate (ranked by relevance):**
{files_section}

**Import chain:**
  {chain_section}

**Recent commits touching these files:**
{commits_section}

**Suggested starting point:**
  {start_section}
"""

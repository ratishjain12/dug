"""Git hook installer — writes post-commit and post-checkout hooks."""

from __future__ import annotations

import os
import stat
from pathlib import Path

_POST_COMMIT = """\
#!/bin/sh
# dug: reindex files changed in this commit
dug update --changed-only
"""

_POST_CHECKOUT = """\
#!/bin/sh
# dug: reindex files that differ after a branch switch
PREV_HEAD="$1"
NEW_HEAD="$2"
IS_BRANCH="$3"
if [ "$IS_BRANCH" = "1" ]; then
    dug update --branch-switch --from="$PREV_HEAD" --to="$NEW_HEAD"
fi
"""

_DUG_MARKER = "# dug:"


def _write_hook(hook_path: Path, content: str) -> str:
    """Append dug block to an existing hook or create a new one."""
    if hook_path.exists():
        existing = hook_path.read_text()
        if _DUG_MARKER in existing:
            return "already installed"
        # Append to existing hook
        updated = existing.rstrip() + "\n\n" + content
        hook_path.write_text(updated)
        return "appended to existing hook"
    else:
        hook_path.write_text(content)
        # Make executable
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return "created"


def install_git_hooks(root: Path) -> dict[str, str]:
    """Install post-commit and post-checkout hooks. Returns status per hook."""
    hooks_dir = root / ".git" / "hooks"
    if not hooks_dir.exists():
        return {"error": "not a git repo or .git/hooks missing"}

    results = {}
    results["post-commit"] = _write_hook(hooks_dir / "post-commit", _POST_COMMIT)
    results["post-checkout"] = _write_hook(hooks_dir / "post-checkout", _POST_CHECKOUT)
    return results


def ensure_gitignore(root: Path) -> str:
    """Add .dug/ to .gitignore if not already present. Returns status string."""
    gitignore = root / ".gitignore"
    entry = ".dug/"

    if gitignore.exists():
        lines = gitignore.read_text().splitlines()
        # Check for exact match or glob that already covers it
        if any(line.strip() in (entry, ".dug", "**/.dug/", "**/.dug") for line in lines):
            return "already in .gitignore"
        # Append with a section comment
        with open(gitignore, "a") as f:
            f.write(f"\n# dug local index — machine-specific, never commit\n{entry}\n")
        return "added to existing .gitignore"
    else:
        gitignore.write_text(f"# dug local index — machine-specific, never commit\n{entry}\n")
        return "created .gitignore"


def uninstall_git_hooks(root: Path) -> dict[str, str]:
    """Remove the dug block from hooks (leaves other hook content intact)."""
    hooks_dir = root / ".git" / "hooks"
    results = {}
    for name, content in [("post-commit", _POST_COMMIT), ("post-checkout", _POST_CHECKOUT)]:
        hook_path = hooks_dir / name
        if not hook_path.exists():
            results[name] = "not found"
            continue
        existing = hook_path.read_text()
        if _DUG_MARKER not in existing:
            results[name] = "not installed"
            continue
        # Remove the dug block
        cleaned = existing.replace("\n\n" + content, "").replace(content, "")
        hook_path.write_text(cleaned)
        results[name] = "removed"
    return results

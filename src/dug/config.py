import json
import subprocess
from pathlib import Path

DEFAULTS = {
    "embedding_mode": "local",
    "api_key": None,
    "languages": ["python", "java", "typescript", "javascript"],
    "ignore_paths": ["node_modules", ".git", "build", "dist", "vendor", "__pycache__", ".venv", "venv", ".tox", "eggs", ".eggs"],
    "git_history_depth": 50,
    "max_files_in_prompt": 5,
    "exclude_test_files": True,
}


def find_repo_root() -> Path:
    """
    Walk up from cwd looking for .git/. Falls back to cwd if not in a git repo.
    Also accepts a repo root that already has .dug/ (supports non-git projects
    that ran dug init manually).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except FileNotFoundError:
        pass

    # Fallback: walk up looking for an existing .dug/ directory
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".dug").exists():
            return parent

    return Path.cwd()


def get_dug_dir() -> Path:
    return find_repo_root() / ".dug"


def get_config_path() -> Path:
    return get_dug_dir() / "config.json"


def load_config() -> dict:
    path = get_config_path()
    if not path.exists():
        return dict(DEFAULTS)
    with open(path) as f:
        data = json.load(f)
    return {**DEFAULTS, **data}


def save_config(cfg: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


def set_config_value(key: str, value: str) -> None:
    cfg = load_config()
    # coerce booleans and nulls
    if value.lower() == "null":
        cfg[key] = None
    elif value.lower() in ("true", "false"):
        cfg[key] = value.lower() == "true"
    else:
        cfg[key] = value
    save_config(cfg)
# phase 4 test comment

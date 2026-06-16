from __future__ import annotations

import logging
import os
import subprocess
import sys
import warnings

# Suppress HuggingFace noise before any library import
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")

for _noisy in ("sentence_transformers", "huggingface_hub", "transformers",
               "torch", "tokenizers"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Dependency installer
# ---------------------------------------------------------------------------

_LOCAL_DEPS  = ["sentence-transformers"]
_OPENAI_DEPS = ["openai"]


def _ensure_installed(packages: list[str], label: str) -> None:
    """Check if packages are importable; pip-install them if not."""
    import importlib
    missing = []
    for pkg in packages:
        module = pkg.replace("-", "_").split("[")[0]
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return

    # PyInstaller binary: sys.executable is the frozen binary, not Python
    if getattr(sys, "frozen", False):
        print(f"\n[dug] Running as a standalone binary — cannot auto-install {label} packages.")
        print(f"[dug] Switch to OpenAI embeddings instead:")
        print(f"      dug config set embedding_mode openai")
        print(f"      dug config set api_key <your-openai-key>")
        print(f"[dug] Or reinstall dug via pipx for local embeddings:")
        print(f"      pipx install dug-cli")
        sys.exit(1)

    print(f"\n[dug] {label} dependencies not found: {', '.join(missing)}")
    print(f"[dug] Installing (one-time download)...\n")

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print(f"\n[dug] ✓ {label} dependencies installed.\n")
    except subprocess.CalledProcessError:
        print(f"\n[dug] ✗ Auto-install failed. Run manually:")
        print(f"      pip install {' '.join(missing)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

class LocalEmbedder:
    def __init__(self):
        _ensure_installed(_LOCAL_DEPS, "Local embedding")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()


class OpenAIEmbedder:
    def __init__(self, api_key: str):
        _ensure_installed(_OPENAI_DEPS, "OpenAI")
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding


_cache: dict = {}


def get_embedder(config: dict) -> LocalEmbedder | OpenAIEmbedder:
    mode = config.get("embedding_mode", "local")
    if mode not in _cache:
        if mode == "openai":
            _cache[mode] = OpenAIEmbedder(api_key=config["api_key"])
        else:
            _cache[mode] = LocalEmbedder()
    return _cache[mode]

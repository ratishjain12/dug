# dug

**Dig into any bug with full codebase context — zero LLM calls.**

[![PyPI version](https://img.shields.io/pypi/v/dug-cli)](https://pypi.org/project/dug-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/dug-cli/)

`dug` takes a bug report or stack trace and generates a structured [Claude Code](https://claude.ai/code) prompt that includes the exact files, functions, and context needed to fix it — using grep, AST parsing, and a local vector index with **no API calls and no LLM required**.

---

## Install

### macOS (Homebrew) — recommended for Mac users
```sh
brew tap ratishjain12/dug
brew trust ratishjain12/dug
brew install dug-cli
```

### pipx — recommended for Python users
```sh
pipx install dug-cli
```

### One-liner (Linux / macOS)
```sh
curl -fsSL https://raw.githubusercontent.com/ratishjain12/dug/main/install.sh | sh
```

### pip (inside a virtualenv)
```sh
pip install dug-cli
```

---

## Update

### Homebrew
```sh
brew update
brew upgrade dug-cli
```

### pipx
```sh
pipx upgrade dug-cli
```

### pip
```sh
pip install --upgrade dug-cli
```

---

## Quick start

```sh
# 1. Run once in your repo root to build the index
cd /your/project
dug init

# 2. Paste any bug report or stack trace
dug "NullPointerException in UserService.authenticate at line 42"

# dug prints a ready-to-paste Claude Code prompt with ranked file context
```

**Sample output:**

```
You are a senior engineer debugging this issue:

  NullPointerException in UserService.authenticate at line 42

Relevant files (ranked by relevance):

1. src/auth/UserService.java:35
   authenticate() — modified 2 commits ago
   ...

2. src/config/AppConfig.java:12
   loadConfig() — error pattern match
   ...

[full function bodies + graph context follow]
```

---

## How it works

`dug` builds a **local knowledge base** the first time you run `dug init`:

| Layer | What it builds | Used for |
|---|---|---|
| Structural graph | File → Symbol → Commit nodes (networkx) | Import chains, recent changes |
| Semantic index | Function embeddings in LanceDB (fastembed / ONNX) | Meaning-level matches |
| History log | Past bug→fix pairs | Learning from outcomes |

At query time, three signals are combined into a ranked list:

- **Structural score** — imports your error file, was modified in a related commit
- **Semantic score** — cosine similarity between bug text and function bodies
- **History boost** — similar past bugs pointed here

Languages auto-detected on `dug init` — no manual config needed. The index stays fresh via git hooks (`post-commit`, `post-checkout`) and an optional file watcher.

---

## Commands

| Command | What it does |
|---|---|
| `dug init` | Index the current repo (auto-detects languages, builds graph + embeddings) |
| `dug "error text"` | Generate a Claude Code prompt for the bug |
| `dug update` | Re-index files changed since last commit |
| `dug watch` | Watch for file saves and re-index in real time |
| `dug stats` | Show index size (nodes, edges, chunks) |
| `dug config` | View / edit configuration |
| `dug feedback good` | Mark last query as helpful (improves future results) |
| `dug feedback bad` | Mark last query as unhelpful |

---

## Configuration

`dug init` creates `.dug/config.json` in the repo root. Languages are auto-detected from your codebase — you rarely need to edit this manually.

```json
{
  "embedding_mode": "local",
  "languages": ["typescript", "javascript"],
  "max_files_in_prompt": 5,
  "git_history_depth": 50,
  "exclude_test_files": true
}
```

`.dug/` is automatically added to `.gitignore` — it's machine-specific and never committed.

---

## Contributing

```sh
git clone https://github.com/ratishjain12/dug
cd dug
uv sync
uv run dug init   # index the dug repo itself
uv run dug "your bug here"
```

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

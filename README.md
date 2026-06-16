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
# 1. Run once in your repo root — auto-detects languages, builds index
cd /your/project
dug init

# 2. Paste any bug report or stack trace
dug "NullPointerException in UserService.authenticate at line 42"

# 3. After you fix the bug, tell dug which files had the fix
dug solved
```

`dug solved` shows what it suggested and lets you confirm or correct:
```
Last query: "NullPointerException in UserService.authenticate at line 42"
Suggested files were:
  - src/auth/UserService.java
  - src/config/AppConfig.java

Which files actually contained the bug? (comma-separated paths)
> src/auth/UserService.java
```

Next time a similar error comes in, that file ranks higher automatically.

**Sample query output:**

```
## Bug Report

**Error:** NullPointerException in UserService.authenticate at line 42
**Error type:** `NullPointerException`

**Files to investigate (ranked by relevance):**
  - src/auth/UserService.java  (modified in relevant recent commit, semantic match 3.4/5)
  - src/config/AppConfig.java  (semantic match 2.1/5)

**Recent commits touching these files:**
  a1b2c3: "fix: add null check in auth flow"  (1d ago)

**Suggested starting point:**
  Begin at src/auth/UserService.java.
```

---

## How it works

`dug` builds a **local knowledge base** the first time you run `dug init`:

| Layer | What it builds | Used for |
|---|---|---|
| Structural graph | File → Symbol → Commit nodes (networkx) | Import chains, recent changes |
| Semantic index | Function embeddings in LanceDB (fastembed / ONNX) | Meaning-level matches |
| History log | Past bug→file resolutions | Learning from outcomes |

At query time, three signals are combined into a ranked list:

- **Structural score** — imports your error file, was modified in a related commit
- **Semantic score** — cosine similarity between bug text and function bodies
- **History boost** — similar past bugs pointed here, scaled by similarity

Languages are auto-detected on `dug init` — no manual config needed. The index stays fresh via git hooks (`post-commit`, `post-checkout`) installed automatically.

---

## Commands

| Command | What it does |
|---|---|
| `dug init` | Interactive setup — auto-detects languages, builds index, installs git hooks |
| `dug "error text"` | Generate a Claude Code prompt for the bug |
| `dug update` | Re-index files changed since last commit (git hooks run this automatically) |
| `dug watch` | Background watcher — reindexes on every file save (1.5s debounce) |
| `dug solved` | Record which files fixed the last bug — improves future rankings |
| `dug solved --files "path1,path2"` | Non-interactive version of `dug solved` |
| `dug stats` | Show index size (nodes, edges, chunks) |
| `dug config` | View / edit configuration |

---

## Configuration

`dug init` creates `.dug/config.json` in the repo root. Languages are auto-detected from your codebase.

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

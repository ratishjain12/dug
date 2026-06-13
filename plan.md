# dug — Build Plan

> A CLI tool that knows your codebase, finds relevant context from any bug or stack trace, and generates a ready-to-paste Claude Code prompt. Zero AI calls. Fully local. Optional embeddings for cloud speed.

---

## What You're Building

```bash
# You run this
$ dug "NullPointerException at PaymentProcessor.java:47"

# You get this — ready to paste into Claude Code
## Bug Report

**Error:** NullPointerException at PaymentProcessor.java:47

**Files to investigate (ranked by relevance):**
  - src/services/PaymentProcessor.java   (directly in stack trace, modified 2 days ago)
  - src/services/UserService.java        (imported by PaymentProcessor, changed in last commit)
  - src/controllers/CheckoutController  (calls PaymentProcessor)

**Import chain:**
  CheckoutController → PaymentProcessor → UserService

**Recent commits touching these files:**
  a3f2b: "refactor UserService.getById() return type"  (2d ago)
  b1c4d: "add null check in checkout flow"             (4d ago)

**Suggested starting point:**
  Begin at PaymentProcessor.java:47.
  It was last modified 2 days ago and imports UserService, PaymentGateway.
```

**Zero LLM calls. Zero API cost. Everything runs locally.**

---

## The Core Principle

dug is not an AI tool. It is a **code intelligence tool** that uses grep, AST parsing, and graph traversal to find what matters — then assembles it into a structured prompt using pure Python.

```
What most people assume:    bug input → LLM → output
What dug actually does:     bug input → graph traversal + search → f-string template → output
```

The heavy lifting is done by tools that have existed for decades. The output just happens to be a perfect Claude Code prompt.

---

## Where LLM Is and Isn't Used

| Step              | Tool                                                 | LLM?                                 |
| ----------------- | ---------------------------------------------------- | ------------------------------------ |
| File walk         | `pathlib`                                            | No                                   |
| Symbol extraction | `ctags` + `ripgrep`                                  | No                                   |
| Import graph      | `ripgrep`                                            | No                                   |
| Git context       | `git log`                                            | No                                   |
| AST chunking      | `tree-sitter`                                        | No                                   |
| Embeddings        | `sentence-transformers` (local) or OpenAI (optional) | Only for embeddings — not generative |
| Hybrid search     | `lancedb` + `networkx`                               | No                                   |
| Verification      | `ripgrep`                                            | No                                   |
| Prompt assembly   | Pure Python f-strings                                | No                                   |

**Embeddings are the only external touchpoint — and they're optional.**
The default path uses `sentence-transformers` which runs fully local on CPU. No API key. No cost. No data leaving the machine.

---

## Tech Stack

| Layer                 | Tool                                         | Purpose                                      |
| --------------------- | -------------------------------------------- | -------------------------------------------- |
| CLI                   | `click`                                      | Commands: init, query, update, watch, config |
| Structural graph      | `networkx` + `ripgrep` + `ctags`             | File, symbol, import relationships           |
| AST parsing           | `tree-sitter`                                | Function-level chunking                      |
| Embeddings (default)  | `sentence-transformers` + `all-MiniLM-L6-v2` | Local, free, no API key                      |
| Embeddings (optional) | OpenAI `text-embedding-3-small`              | Faster, cloud-based, ~$0 cost                |
| Vector store          | `lancedb`                                    | Local file-based, no server needed           |
| File watching         | `watchdog`                                   | Incremental updates on save                  |
| Git context           | `subprocess` + `git log`                     | Recent commit awareness                      |
| Prompt assembly       | Pure Python                                  | Zero LLM — just structured f-strings         |

---

## Project Structure

```
dug/
  __main__.py          ← CLI entry (click commands)
  config.py            ← config management
  indexer.py           ← init + update logic
  graph.py             ← structural graph (Layer 1)
  embeddings.py        ← vector index (Layer 2)
  watcher.py           ← file system watcher
  retriever.py         ← hybrid search + reranking
  verifier.py          ← ripgrep verification before output
  prompt_builder.py    ← pure Python prompt assembly
  git_context.py       ← git log parsing

.dug/                  ← lives in your project root, gitignored
  config.json          ← embedding mode, languages, ignore paths
  graph.json           ← structural graph (nodes + edges)
  embeddings/          ← lancedb vector store
  hashes.json          ← file hash cache for incremental updates
  history.json         ← past bugs + files that resolved them
```

---

## Embedding Options — Simple Choice at Init

```
$ dug init

Embedding mode:
  1. Local  — sentence-transformers, no API key, runs on CPU  (recommended)
  2. OpenAI — text-embedding-3-small, needs API key, faster

> 1

✓ Using local embeddings. No API key needed.
Starting index...
```

```python
# embeddings.py — clean separation, swap without touching anything else

class LocalEmbedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("all-MiniLM-L6-v2")  # 80MB, CPU-friendly

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()


class OpenAIEmbedder:
    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding


def get_embedder(config):
    if config["embedding_mode"] == "openai":
        return OpenAIEmbedder(api_key=config["api_key"])
    return LocalEmbedder()   # default
```

---

## Config Schema

```json
{
  "embedding_mode": "local",
  "api_key": null,
  "languages": ["python", "java", "typescript", "javascript"],
  "ignore_paths": [
    "node_modules",
    ".git",
    "build",
    "dist",
    "vendor",
    "__pycache__"
  ],
  "git_history_depth": 50,
  "max_files_in_prompt": 5
}
```

---

## Incremental Update Strategy

**Golden rule: embeddings only run on what actually changed.**

Three guards before any embedding call:

```
Guard 1: File hash       → skip entire file if content unchanged
Guard 2: Function diff   → skip unchanged functions within a changed file
Guard 3: Chunk cache     → skip embedding if this exact function was seen before
```

```python
# Guard 1 — file level
def needs_reindex(filepath):
    current = hashlib.md5(open(filepath, 'rb').read()).hexdigest()
    stored = load_hashes().get(str(filepath))
    return current != stored

# Guard 2 — function level
def get_changed_functions(filepath):
    changed_lines = get_git_diff_lines(filepath)
    all_functions = tree_sitter_parse(filepath)
    return [
        fn for fn in all_functions
        if lines_overlap(fn.start_line, fn.end_line, changed_lines)
    ]

# Guard 3 — chunk level
def get_or_embed(embedder, function_code):
    chunk_hash = md5(function_code.encode()).hexdigest()
    cached = chunk_cache.get(chunk_hash)
    if cached:
        return cached                          # no embedding call
    vector = embedder.embed(function_code)
    chunk_cache.set(chunk_hash, vector)
    return vector
```

**Real numbers after first init:**

| Event                               | Embedding calls                  |
| ----------------------------------- | -------------------------------- |
| `dug init` on 500-function codebase | 500 (one time only)              |
| Edit 1 function + save              | 1                                |
| Commit touching 5 functions         | 5                                |
| Edit whitespace / formatting only   | 0                                |
| Switch git branch                   | 10–30 (only differing functions) |

Daily embedding usage is typically under 10 calls. At local speed — milliseconds. At OpenAI pricing — fractions of a cent.

---

## Prompt Assembly — Pure Python

No LLM. No API call. Just data you already have, formatted cleanly.

```python
# prompt_builder.py
def build_prompt(bug_input, ranked_files, git_commits, signals):
    files_section = "\n".join([
        f"  - {f.path}   ({f.reason}, modified {f.last_modified})"
        for f in ranked_files
    ])

    chain = ranked_files[0].import_chain if ranked_files else []
    chain_section = " → ".join(chain) if chain else "n/a"

    commits_section = "\n".join([
        f"  {c.hash[:7]}: \"{c.message}\"  ({c.days_ago}d ago)"
        for c in git_commits[:3]
    ])

    start = ranked_files[0] if ranked_files else None
    start_section = (
        f"Begin at {start.path}.\n"
        f"  Last modified {start.last_modified}. "
        f"Imports: {', '.join(start.imports[:3])}."
    ) if start else "No clear starting point found."

    return f"""## Bug Report

**Error:** {bug_input}

**Files to investigate (ranked by relevance):**
{files_section}

**Import chain:**
  {chain_section}

**Recent commits touching these files:**
{commits_section}

**Suggested starting point:**
  {start_section}
"""
```

---

## Phase 0 — Foundation

**Time: 1 day**
**Goal: Project runs, CLI works, embedding mode selected, config saved.**

### Tasks

- [ ] Scaffold full project structure
- [ ] Set up `click` CLI with placeholder commands: `init`, `query`, `update`, `watch`, `config`
- [ ] Write `config.py` — loads/saves `.dug/config.json`
- [ ] Write `embeddings.py` — both `LocalEmbedder` and `OpenAIEmbedder`
- [ ] Install dependencies

```bash
pip install click networkx tree-sitter tree-sitter-python \
            tree-sitter-java lancedb watchdog \
            sentence-transformers openai
```

### Setup Wizard

```
$ dug init

Welcome to dug.

Embedding mode:
  1. Local  — no API key, runs on CPU  (recommended)
  2. OpenAI — needs API key, faster

> 1

✓ Using local embeddings. No API key needed.

Languages detected: python, typescript
Ignore paths: node_modules, .git, build, dist

Starting initial index...
████████████████████ 100%  312 files indexed

✓ dug is ready. Run: dug "your error here"
```

### Checkpoint

`dug --help` prints all commands. Setup wizard completes. Embedder initializes without errors. Config saved to `.dug/config.json`.

---

## Phase 1 — Structural Graph

**Time: 1 week**
**Goal: `dug init` builds a knowledge graph from your codebase using grep and ctags. No LLM.**

### Node and Edge Types

```
Nodes:   FILE    — path, language, last_modified, size
         SYMBOL  — name, kind (fn/class/method), file, line_number
         COMMIT  — hash, message, timestamp, files_touched

Edges:   FILE   → SYMBOL   (contains)
         SYMBOL → SYMBOL   (calls)
         FILE   → FILE     (imports)
         COMMIT → FILE     (modified)
```

### Day 1–2: File walk + FILE nodes

- [ ] Walk repo recursively, skip `ignore_paths`
- [ ] Create one FILE node per source file
- [ ] Store: path, language, last_modified, size

```python
def walk_repo(root, ignore_paths):
    for path in Path(root).rglob("*"):
        if path.is_file() and not any(ig in str(path) for ig in ignore_paths):
            yield path
```

### Day 3–4: Symbol extraction + SYMBOL nodes

- [ ] Run ctags for primary symbol extraction
- [ ] Create SYMBOL node per function, class, method
- [ ] Link FILE → SYMBOL edges

```bash
ctags -R --output-format=json --fields=+n .
# Output: name, kind, file, line number for every symbol
```

- [ ] Fallback: ripgrep for languages ctags misses

```bash
rg "^def |^class |^function |^public |^private " --json
```

### Day 5: Import graph + FILE→FILE edges

- [ ] Grep import statements per language
- [ ] Link FILE → FILE edges — your dependency graph

```bash
rg "^import |^from .+ import" --json    # Python
rg "^import |require\(" --json          # JS/TS
rg "^import " --json                    # Java
```

### Day 6–7: Git history + COMMIT nodes

- [ ] Parse last N commits from `git log`
- [ ] Create COMMIT nodes: hash, message, timestamp
- [ ] Link COMMIT → FILE for each touched file
- [ ] Recent commits get higher relevance weight in scoring

```python
def get_git_history(depth=50):
    result = subprocess.run(
        ["git", "log", "--name-only", "--format=%H|%s|%ai", f"-n{depth}"],
        capture_output=True, text=True
    )
    return parse_git_output(result.stdout)
```

### Checkpoint

`dug init` runs on your own project. Prints graph stats — FILE nodes, SYMBOL nodes, COMMIT nodes, total edges. Verify 3 files look correct in the graph.

---

## Phase 2 — Semantic Index

**Time: 1 week**
**Goal: Every function is embedded. Semantic search works. Embeddings only run on changed code.**

### Why this layer exists

The structural graph finds exact matches — if the trace says `PaymentProcessor` it finds it instantly. The semantic layer handles vague bugs — "checkout is failing" — where you don't know the function name.

### Day 1–2: Tree-sitter chunking

- [ ] Parse each file using Tree-sitter
- [ ] Extract individual function bodies as chunks — not whole files
- [ ] Chunk size target: 100–1000 characters
- [ ] Store per chunk: chunk_id, file_path, function_name, start_line, end_line, raw_code

```python
from tree_sitter import Language, Parser

def extract_functions(filepath, language):
    parser = get_parser(language)
    tree = parser.parse(open(filepath).read().encode())
    return extract_function_nodes(tree.root_node, filepath)
```

### Day 3–4: LanceDB setup + embed chunks

- [ ] Initialize LanceDB at `.dug/embeddings/`
- [ ] Table schema: chunk_id, file_path, function_name, vector
- [ ] Embed each function body using configured embedder
- [ ] Apply Guard 3 — skip if chunk hash already in cache

```python
import lancedb

db = lancedb.connect(".dug/embeddings")
table = db.create_table("functions", data=rows, schema=SCHEMA)
```

### Day 5–7: Semantic search working

- [ ] Embed the incoming bug query using same embedder
- [ ] Cosine similarity search against stored vectors
- [ ] Return top 10 most semantically similar functions

```python
def semantic_search(embedder, query, top_k=10):
    query_vector = embedder.embed(query)
    return table.search(query_vector).limit(top_k).to_df()
```

### Checkpoint

Type: `"checkout is failing with a null value"`. Semantic search returns functions related to checkout, payment, or null handling — without those exact words in the function names.

---

## Phase 3 — Hybrid Retrieval + Prompt Assembly

**Time: 1 week**
**Goal: `dug "error"` outputs a verified, structured Claude Code prompt. Zero LLM calls.**

### Day 1–2: Signal extraction from bug input

- [ ] Extract signals from raw bug or stack trace — pure regex, no LLM
- [ ] File names, class names, function names, line numbers
- [ ] Error type classification (NPE, timeout, KeyError, 404, etc.)

```python
def extract_signals(bug_input):
    return {
        "files":      re.findall(r'[\w/]+\.(java|py|ts|js)', bug_input),
        "symbols":    re.findall(r'at (\w+)\(', bug_input),
        "lines":      re.findall(r':(\d+)', bug_input),
        "error_type": classify_error_type(bug_input)
    }
```

### Day 3: Hybrid search — merge both layers

- [ ] Layer 1: structural graph lookup for extracted symbols
- [ ] Layer 2: semantic search on raw bug input
- [ ] Score and merge results

```python
def hybrid_search(embedder, bug_input):
    signals = extract_signals(bug_input)

    # Layer 1 — structural, exact
    structural = graph.find_nodes(signals["symbols"] + signals["files"])

    # Layer 2 — semantic, fuzzy
    semantic = semantic_search(embedder, bug_input, top_k=10)

    # Merge scores
    scores = {}
    for hit in structural:
        scores[hit.file] = scores.get(hit.file, 0) + structural_score(hit)
    for hit in semantic.itertuples():
        scores[hit.file_path] = scores.get(hit.file_path, 0) + hit.score * 5

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
```

### Scoring weights

| Signal                               | Score    |
| ------------------------------------ | -------- |
| Directly mentioned in stack trace    | +10      |
| Modified in last 3 commits           | +8       |
| 1-hop import neighbor                | +5       |
| Semantic similarity (normalized 0–1) | +0 to +5 |
| Previously fixed similar bug         | +6       |
| 2-hop import neighbor                | +2       |

### Day 4: Verifier — no false positives

- [ ] Before assembling prompt, verify each candidate file actually contains the symbols
- [ ] Pure ripgrep — takes milliseconds
- [ ] Drop files that fail verification

```python
def verify_files(candidate_files, symbols):
    confirmed = []
    for filepath in candidate_files:
        for symbol in symbols:
            result = subprocess.run(["rg", symbol, filepath], capture_output=True)
            if result.returncode == 0:
                confirmed.append(filepath)
                break
    return confirmed
```

### Day 5–7: Prompt assembly — pure Python

- [ ] Take top 5 verified files + import chain + git context
- [ ] Format into structured template — zero LLM
- [ ] Output to stdout — user copies into Claude Code

```python
def build_prompt(bug_input, ranked_files, git_commits, signals):
    files_section = "\n".join([
        f"  - {f.path}   ({f.reason}, modified {f.last_modified})"
        for f in ranked_files
    ])
    chain_section = " → ".join(ranked_files[0].import_chain) if ranked_files else "n/a"
    commits_section = "\n".join([
        f"  {c.hash[:7]}: \"{c.message}\"  ({c.days_ago}d ago)"
        for c in git_commits[:3]
    ])
    start = ranked_files[0] if ranked_files else None
    return f"""## Bug Report

**Error:** {bug_input}

**Files to investigate (ranked by relevance):**
{files_section}

**Import chain:**
  {chain_section}

**Recent commits touching these files:**
{commits_section}

**Suggested starting point:**
  Begin at {start.path if start else 'unknown'}.
"""
```

### Checkpoint

Feed 5 real bugs from your own work. Every output points to the right files. Zero false positives. Zero API calls made.

---

## Phase 4 — Incremental Updates

**Time: 1 week**
**Goal: Graph and index stay fresh automatically. Embeddings only run on what changed.**

### Day 1–2: Hash-based file cache

- [ ] MD5 hash every source file on update
- [ ] Compare against `.dug/hashes.json`
- [ ] Skip entire file if hash unchanged — Guard 1

```python
def needs_reindex(filepath):
    current = hashlib.md5(open(filepath, 'rb').read()).hexdigest()
    stored = load_hashes().get(str(filepath))
    return current != stored
```

### Day 3: Git post-commit hook

- [ ] `dug init` auto-installs this hook
- [ ] After every commit: get changed files from `git diff HEAD~1 --name-only`
- [ ] Re-index only those files at function level
- [ ] Add new COMMIT node + edges

```bash
# .git/hooks/post-commit  (auto-installed by dug init)
#!/bin/sh
dug update --changed-only
```

### Day 4–5: File watcher daemon

- [ ] `dug watch` starts background process
- [ ] `watchdog` monitors source directories
- [ ] On file save → surgical update of only that file's nodes and embeddings

```python
class CodeChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if is_source_file(event.src_path) and needs_reindex(event.src_path):
            indexer.update_file(event.src_path)
```

### Day 6: Branch switch handling

- [ ] Git post-checkout hook detects branch switch
- [ ] Gets files differing between branches
- [ ] Reindexes only those files

```bash
# .git/hooks/post-checkout
#!/bin/sh
PREV=$1; NEW=$2; IS_BRANCH=$3
if [ "$IS_BRANCH" = "1" ]; then
    dug update --branch-switch --from=$PREV --to=$NEW
fi
```

### Day 7: Stale node pruning

- [ ] On every update, check if each FILE node still exists on disk
- [ ] Remove nodes for deleted or renamed files

```python
def prune_stale_nodes():
    for node in graph.file_nodes():
        if not Path(node.path).exists():
            graph.remove(node)
```

### Checkpoint

Edit a file and save — graph updates within 2 seconds. Commit a change — reflected immediately. Delete a file — gone from graph on next update.

---

## Phase 5 — Learning Loop

**Time: 1 week**
**Goal: dug gets smarter per project the more you use it. Still zero LLM.**

### Day 1–3: Feedback capture

- [ ] After fixing a bug, run `dug solved`
- [ ] Records which files actually contained the fix
- [ ] Writes to `.dug/history.json`

```bash
$ dug solved
Which files actually contained the bug? (comma separated)
> src/services/PaymentProcessor.java, src/services/UserService.java
✓ Saved. These files will rank higher for similar errors next time.
```

### Day 4–5: History boost in scoring

- [ ] Compare new bug against past entries in `history.json`
- [ ] Boost files that resolved similar past bugs by +6
- [ ] Pure string similarity — no LLM

```python
def get_history_boost(bug_input, candidate_files):
    similar = find_similar_past_bugs(bug_input)   # string similarity
    boosts = {}
    for past in similar:
        for filepath in past["resolved_files"]:
            if filepath in candidate_files:
                boosts[filepath] = boosts.get(filepath, 0) + 6
    return boosts
```

### Day 6–7: Error pattern library

- [ ] Accumulate error type → commonly involved files from your history
- [ ] "DB timeout" always surfaces your connection pool config
- [ ] Learned from your project — not generic rules

### Checkpoint

Feed a bug similar to one you've solved before. Previously-helpful files rank higher than a fresh search gives them.

---

## Phase 6 — Distribution

**Time: 1 weekend**
**Goal: Anyone on Mac or Windows installs dug in one command.**

### Ship order — do not skip ahead

| Order | Method                 | Time    | Covers             |
| ----- | ---------------------- | ------- | ------------------ |
| 1     | `pipx install dug-cli` | 2 hours | Anyone with Python |
| 2     | `curl` install script  | 3 hours | Mac + Linux + WSL  |
| 3     | `brew install dug`     | 3 hours | Mac developers     |
| 4     | `scoop install dug`    | 2 hours | Windows developers |

### Step 1 — PyPI

```toml
# pyproject.toml
[project]
name = "dug-cli"
version = "0.1.0"
description = "Dig into any bug with full codebase context"
requires-python = ">=3.10"

[project.scripts]
dug = "dug.__main__:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

```bash
pip install hatch && hatch build && hatch publish

# Users install with:
pipx install dug-cli
```

### Step 2 — curl install script

```bash
# What users run
curl -fsSL https://getdug.dev/install.sh | sh
```

```bash
# install.sh
#!/bin/sh
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)        ARCH="amd64" ;;
  arm64|aarch64) ARCH="arm64" ;;
esac
URL="https://github.com/yourusername/dug/releases/latest/download/dug-${OS}-${ARCH}"
curl -fsSL "$URL" -o /usr/local/bin/dug && chmod +x /usr/local/bin/dug
echo "✓ dug installed"
```

Build cross-platform binaries via GitHub Actions:

```yaml
# .github/workflows/release.yml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
steps:
  - run: pip install pyinstaller
  - run: pyinstaller --onefile dug/__main__.py --name dug
```

### Step 3 — Homebrew tap (Mac)

Create repo: `github.com/yourusername/homebrew-dug`

```ruby
class Dug < Formula
  desc "Dig into any bug with full codebase context"
  homepage "https://getdug.dev"
  version "0.1.0"

  on_macos do
    on_arm   { url "...dug-darwin-arm64"; sha256 "abc..." }
    on_intel { url "...dug-darwin-amd64"; sha256 "def..." }
  end

  def install
    bin.install Dir["dug-darwin-*"].first => "dug"
  end
end
```

```bash
brew tap yourusername/dug && brew install dug
```

### Step 4 — Scoop (Windows)

Create repo: `github.com/yourusername/scoop-dug`

```json
{
  "version": "0.1.0",
  "description": "Dig into any bug with full codebase context",
  "homepage": "https://getdug.dev",
  "architecture": {
    "64bit": {
      "url": "https://github.com/yourusername/dug/releases/download/v0.1.0/dug-windows-amd64.exe",
      "hash": "abc123..."
    }
  },
  "bin": "dug-windows-amd64.exe"
}
```

```bash
scoop bucket add dug https://github.com/yourusername/scoop-dug
scoop install dug
```

### Landing page — getdug.dev

Register domain (~$12/year). One page:

- One sentence: what it does
- Install command, copy-paste ready
- 30-second GIF of `dug` running on a real bug
- Link to GitHub

---

## Build-in-Public Content — One Post Per Week

| Week | Post                                                                                          |
| ---- | --------------------------------------------------------------------------------------------- |
| 0    | "I built a tool that generates Claude Code bug context with zero AI calls. Here's how."       |
| 1    | "I built a codebase knowledge graph using ripgrep and ctags. Took one weekend."               |
| 2    | "I added semantic search to dug using local embeddings. No API key, runs on CPU."             |
| 3    | "dug generates a perfect prompt using pure Python f-strings. No LLM in the output step."      |
| 4    | "Git hooks + file watchers: how dug updates itself after every commit automatically."         |
| 5    | "dug now gets smarter every time you fix a bug. Here's the feedback loop — still zero LLM."   |
| 6    | "dug is now on Homebrew and Scoop. Here's how I published a cross-platform CLI in a weekend." |

---

## Quick Reference — Commands

```bash
dug init                    # first-time setup — wizard + full index build
dug "NPE at Foo.java:47"    # main command — outputs Claude Code prompt
dug update                  # manual refresh of graph + index
dug update --changed-only   # reindex only git-changed files
dug watch                   # start background file watcher
dug solved                  # capture feedback after fixing a bug
dug stats                   # print graph stats (nodes, edges, last updated)
dug config set embedding-mode openai
dug config set api-key sk-...
```

---

## What You Have After 6 Weeks

- A CLI that generates perfect Claude Code prompts with zero LLM calls
- Fully local by default — no API key, no cost, no data leaving the machine
- Optional OpenAI embeddings for users who want cloud speed
- Updates itself after every save and commit — embeddings only run on changed functions
- Gets smarter the more you use it on your own projects
- Ships on Mac (brew), Windows (scoop), and everywhere else (pipx + curl)
- A 6-week build-in-public thread documenting every technical decision
- A strong resume project covering AST parsing, graph traversal, vector embeddings, hybrid retrieval, incremental indexing, and cross-platform CLI distribution

---

## The Honest Marketing Line

> _"dug generates a perfect Claude Code prompt using grep, ctags, and graph traversal.
> No AI in the middle. Just your codebase, understood."_

"""Structural knowledge graph — FILE, SYMBOL, and COMMIT nodes with edges."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from .git_context import Commit, get_git_history

# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

LANG_EXTENSIONS: dict[str, list[str]] = {
    "python":     [".py"],
    "java":       [".java"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
}

IMPORT_PATTERNS: dict[str, list[str]] = {
    "python":     [r"^import\s+\S+", r"^from\s+\S+\s+import"],
    "java":       [r"^import\s+\S+"],
    "typescript": [r"^import\s+", r'require\('],
    "javascript": [r"^import\s+", r'require\('],
}


def _ext_to_lang(ext: str) -> str | None:
    for lang, exts in LANG_EXTENSIONS.items():
        if ext in exts:
            return lang
    return None


# ---------------------------------------------------------------------------
# Node dataclasses (stored as node attributes in networkx)
# ---------------------------------------------------------------------------

@dataclass
class FileNode:
    path: str          # relative to repo root
    language: str
    last_modified: float
    size: int


@dataclass
class SymbolNode:
    name: str
    kind: str          # function / class / method
    file_path: str
    line_number: int


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

class CodeGraph:
    def __init__(self):
        self.g: nx.DiGraph = nx.DiGraph()

    # -- persistence -------------------------------------------------------

    def save(self, path: Path) -> None:
        data = nx.node_link_data(self.g)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        with open(path) as f:
            data = json.load(f)
        self.g = nx.node_link_graph(data)

    # -- file nodes --------------------------------------------------------

    def add_file(self, path: Path, root: Path) -> str:
        rel = str(path.relative_to(root))
        lang = _ext_to_lang(path.suffix) or "unknown"
        stat = path.stat()
        node_id = f"file:{rel}"
        self.g.add_node(
            node_id,
            kind="FILE",
            path=rel,
            language=lang,
            last_modified=stat.st_mtime,
            size=stat.st_size,
        )
        return node_id

    def file_nodes(self) -> list[dict]:
        return [
            {"id": n, **d}
            for n, d in self.g.nodes(data=True)
            if d.get("kind") == "FILE"
        ]

    # -- symbol nodes ------------------------------------------------------

    def add_symbol(self, name: str, kind: str, file_path: str, line: int) -> str:
        node_id = f"sym:{file_path}:{name}:{line}"
        self.g.add_node(
            node_id,
            kind="SYMBOL",
            name=name,
            symbol_kind=kind,
            file_path=file_path,
            line_number=line,
        )
        file_id = f"file:{file_path}"
        if self.g.has_node(file_id):
            self.g.add_edge(file_id, node_id, rel="contains")
        return node_id

    # -- import edges ------------------------------------------------------

    def add_import_edge(self, from_file: str, to_file: str) -> None:
        src = f"file:{from_file}"
        dst = f"file:{to_file}"
        if self.g.has_node(src) and self.g.has_node(dst):
            self.g.add_edge(src, dst, rel="imports")

    # -- commit nodes ------------------------------------------------------

    def add_commit(self, commit: Commit, root: Path) -> str:
        node_id = f"commit:{commit.hash}"
        self.g.add_node(
            node_id,
            kind="COMMIT",
            hash=commit.hash,
            message=commit.message,
            timestamp=commit.timestamp.isoformat(),
        )
        for rel_path in commit.files_touched:
            file_id = f"file:{rel_path}"
            if self.g.has_node(file_id):
                self.g.add_edge(node_id, file_id, rel="modified")
        return node_id

    # -- lookup helpers ----------------------------------------------------

    def find_file_nodes_for_symbol(self, symbol: str) -> list[str]:
        results = []
        for n, d in self.g.nodes(data=True):
            if d.get("kind") == "SYMBOL" and d.get("name") == symbol:
                file_id = f"file:{d['file_path']}"
                if file_id not in results:
                    results.append(file_id)
        return results

    def get_import_neighbors(self, file_id: str, hops: int = 2) -> dict[str, int]:
        """Return file_ids reachable within `hops` import edges, with hop distance."""
        visited: dict[str, int] = {}
        frontier = [file_id]
        for hop in range(1, hops + 1):
            next_frontier = []
            for node in frontier:
                for neighbor in list(self.g.successors(node)) + list(self.g.predecessors(node)):
                    if self.g.nodes[neighbor].get("kind") == "FILE" and neighbor not in visited:
                        visited[neighbor] = hop
                        next_frontier.append(neighbor)
            frontier = next_frontier
        return visited

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for _, d in self.g.nodes(data=True):
            k = d.get("kind", "UNKNOWN")
            kinds[k] = kinds.get(k, 0) + 1
        return {"nodes": dict(kinds), "edges": self.g.number_of_edges()}


# ---------------------------------------------------------------------------
# Walk + symbol extraction
# ---------------------------------------------------------------------------

def _should_ignore(path: Path, ignore_paths: list[str]) -> bool:
    path_str = str(path)
    return any(ig in path.parts or ig in path_str for ig in ignore_paths)


def walk_repo(root: Path, ignore_paths: list[str], languages: list[str]) -> list[Path]:
    valid_exts: set[str] = set()
    for lang in languages:
        valid_exts.update(LANG_EXTENSIONS.get(lang, []))

    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in valid_exts and not _should_ignore(p, ignore_paths):
            files.append(p)
    return files


def extract_symbols_ctags(root: Path) -> list[dict]:
    """Run universal-ctags and parse JSON output."""
    try:
        result = subprocess.run(
            ["ctags", "-R", "--output-format=json", "--fields=+n", "."],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    symbols = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("_type") != "tag":
                continue
            symbols.append({
                "name": obj.get("name", ""),
                "kind": obj.get("kind", "unknown"),
                "file": obj.get("path", ""),
                "line": obj.get("line", 0),
            })
        except json.JSONDecodeError:
            continue
    return symbols


def extract_symbols_ripgrep(file_path: Path, root: Path) -> list[dict]:
    """Fallback symbol extraction using ripgrep patterns."""
    patterns = [
        (r"^def ([A-Za-z_]\w*)\s*\(", "function"),
        (r"^class ([A-Za-z_]\w*)\s*[:(]", "class"),
        (r"^function ([A-Za-z_]\w*)\s*\(", "function"),
        (r"^\s+(?:public|private|protected)\s+\w+\s+([A-Za-z_]\w*)\s*\(", "method"),
    ]
    rel = str(file_path.relative_to(root))
    symbols = []
    for pattern, kind in patterns:
        try:
            result = subprocess.run(
                ["rg", "--line-number", "--no-heading", pattern, str(file_path)],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                parts = line.split(":", 1)
                if len(parts) < 2:
                    continue
                try:
                    lineno = int(parts[0])
                except ValueError:
                    continue
                content = parts[1]
                match = re.search(pattern, content)
                if match:
                    symbols.append({
                        "name": match.group(1),
                        "kind": kind,
                        "file": rel,
                        "line": lineno,
                    })
        except FileNotFoundError:
            break
    return symbols


def extract_imports(file_path: Path, root: Path, language: str) -> list[str]:
    """Return list of imported module/file strings found in `file_path`."""
    patterns = IMPORT_PATTERNS.get(language, [])
    imports = []
    for pattern in patterns:
        try:
            result = subprocess.run(
                ["rg", "--no-heading", "--no-line-number", pattern, str(file_path)],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                imports.append(line.strip())
        except FileNotFoundError:
            break
    return imports


def _resolve_import_to_file(import_line: str, all_file_rels: set[str], language: str) -> str | None:
    """Best-effort: map an import statement to a file node path."""
    # Python: "from dug.graph import CodeGraph" → look for dug/graph.py
    # Java: "import com.example.Foo" → com/example/Foo.java
    # JS/TS: "import ... from './utils'" → utils.ts / utils.js
    if language == "python":
        m = re.search(r"^from ([\w.]+) import|^import ([\w.]+)", import_line)
        if m:
            mod = (m.group(1) or m.group(2)).replace(".", "/")
            for ext in [".py"]:
                candidate = mod + ext
                if candidate in all_file_rels:
                    return candidate
    elif language in ("typescript", "javascript"):
        m = re.search(r"""from\s+['"]([^'"]+)['"]""", import_line)
        if m:
            raw = m.group(1)
            for ext in [".ts", ".tsx", ".js", ".jsx"]:
                candidate = raw.lstrip("./") + ext
                for f in all_file_rels:
                    if f.endswith(candidate):
                        return f
    elif language == "java":
        m = re.search(r"^import\s+([\w.]+);", import_line)
        if m:
            candidate = m.group(1).replace(".", "/") + ".java"
            if candidate in all_file_rels:
                return candidate
    return None


# ---------------------------------------------------------------------------
# Public build function
# ---------------------------------------------------------------------------

def build_graph(root: Path, config: dict) -> CodeGraph:
    ignore_paths = config.get("ignore_paths", [])
    languages = config.get("languages", [])
    git_depth = config.get("git_history_depth", 50)

    graph = CodeGraph()
    files = walk_repo(root, ignore_paths, languages)

    # FILE nodes
    for f in files:
        graph.add_file(f, root)

    all_file_rels: set[str] = {str(f.relative_to(root)) for f in files}

    # SYMBOL nodes — try ctags first, fall back to ripgrep per file
    ctags_symbols = extract_symbols_ctags(root)
    if ctags_symbols:
        for sym in ctags_symbols:
            rel = sym["file"]
            if rel in all_file_rels:
                graph.add_symbol(sym["name"], sym["kind"], rel, sym["line"])
    else:
        for f in files:
            lang = _ext_to_lang(f.suffix)
            if lang:
                for sym in extract_symbols_ripgrep(f, root):
                    graph.add_symbol(sym["name"], sym["kind"], sym["file"], sym["line"])

    # FILE→FILE import edges
    for f in files:
        lang = _ext_to_lang(f.suffix)
        if not lang:
            continue
        imports = extract_imports(f, root, lang)
        rel = str(f.relative_to(root))
        for imp in imports:
            target = _resolve_import_to_file(imp, all_file_rels, lang)
            if target and target != rel:
                graph.add_import_edge(rel, target)

    # COMMIT nodes
    for commit in get_git_history(root, depth=git_depth):
        graph.add_commit(commit, root)

    return graph

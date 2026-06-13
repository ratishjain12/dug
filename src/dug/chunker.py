"""Tree-sitter based function/method extractor — produces chunks for embedding."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser, Node

import tree_sitter_python as tspython
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript

# ---------------------------------------------------------------------------
# Language parsers
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, Language] = {
    "python":     Language(tspython.language()),
    "java":       Language(tsjava.language()),
    "javascript": Language(tsjavascript.language()),
    "typescript": Language(tstypescript.language_typescript()),
    "tsx":        Language(tstypescript.language_tsx()),
}

_EXT_TO_LANG: dict[str, str] = {
    ".py":  "python",
    ".java": "java",
    ".js":  "javascript",
    ".jsx": "javascript",
    ".ts":  "typescript",
    ".tsx": "tsx",
}

# Node types that represent callable units worth embedding
_FUNCTION_NODE_TYPES: dict[str, set[str]] = {
    "python":     {"function_definition", "decorated_definition"},
    "java":       {"method_declaration", "constructor_declaration"},
    "javascript": {"function_declaration", "method_definition", "arrow_function",
                   "function_expression"},
    "typescript": {"function_declaration", "method_definition", "arrow_function",
                   "function_expression", "method_signature"},
    "tsx":        {"function_declaration", "method_definition", "arrow_function",
                   "function_expression", "method_signature"},
}

MIN_CHUNK_CHARS = 30
MAX_CHUNK_CHARS = 8000


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    chunk_id: str       # md5(file_path + function_name + str(start_line))
    file_path: str      # relative to repo root
    function_name: str
    start_line: int     # 1-indexed
    end_line: int
    code: str
    language: str


def _make_chunk_id(file_path: str, name: str, start_line: int) -> str:
    key = f"{file_path}:{name}:{start_line}"
    return hashlib.md5(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# AST walker
# ---------------------------------------------------------------------------

def _get_function_name(node: Node, code_bytes: bytes, language: str) -> str:
    """Extract the best available name for a function/method node."""
    # decorated_definition wraps the actual function — recurse one level
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type == "function_definition":
                return _get_function_name(child, code_bytes, language)

    name_node = node.child_by_field_name("name")
    if name_node:
        return code_bytes[name_node.start_byte:name_node.end_byte].decode(errors="replace")

    # arrow functions often have no name — use parent context if available
    return "<anonymous>"


def _walk(node: Node, code_bytes: bytes, language: str,
          target_types: set[str], results: list[Chunk], file_path: str) -> None:
    if node.type in target_types:
        name = _get_function_name(node, code_bytes, language)
        code = code_bytes[node.start_byte:node.end_byte].decode(errors="replace")
        if MIN_CHUNK_CHARS <= len(code) <= MAX_CHUNK_CHARS and name != "<anonymous>":
            results.append(Chunk(
                chunk_id=_make_chunk_id(file_path, name, node.start_point[0] + 1),
                file_path=file_path,
                function_name=name,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                code=code,
                language=language,
            ))
        # still recurse — nested functions/methods should also be extracted
    for child in node.children:
        _walk(child, code_bytes, language, target_types, results, file_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_chunks(file_path: Path, root: Path) -> list[Chunk]:
    """Parse `file_path` with tree-sitter and return one Chunk per function/method."""
    lang = _EXT_TO_LANG.get(file_path.suffix)
    if lang is None or lang not in _LANGUAGES:
        return []

    language = _LANGUAGES[lang]
    parser = Parser(language)

    try:
        code_bytes = file_path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(code_bytes)
    rel = str(file_path.relative_to(root))
    target_types = _FUNCTION_NODE_TYPES.get(lang, set())

    results: list[Chunk] = []
    _walk(tree.root_node, code_bytes, lang, target_types, results, rel)
    return results

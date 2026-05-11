"""Shared tree-sitter loader.

Uses tree-sitter-language-pack so we don't have to compile grammars manually.
"""

from __future__ import annotations

from functools import lru_cache

from tree_sitter import Language, Parser


@lru_cache(maxsize=32)
def get_ts_parser(language: str) -> Parser:
    from tree_sitter_language_pack import get_language  # pyright: ignore[reportMissingImports]

    lang: Language = get_language(language)
    p = Parser()
    p.language = lang
    return p


def walk(node):
    """Iterative DFS over a tree-sitter syntax tree."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def node_text(source: bytes, node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

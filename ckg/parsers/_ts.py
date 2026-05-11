"""Shared tree-sitter loader.

Uses tree-sitter-language-pack so we don't have to compile grammars manually.
"""

from __future__ import annotations

from functools import lru_cache

from tree_sitter import Parser


@lru_cache(maxsize=32)
def get_ts_parser(language: str) -> Parser:
    # `tree-sitter-language-pack`'s exported `get_parser()` returns a fully
    # configured `tree_sitter.Parser` for the requested language. We previously
    # tried the two-step `get_language() + Parser(); p.language = lang` dance,
    # which fails on newer tree-sitter releases — the language-pack's grammar
    # object is its own type and `Parser.language` only accepts a
    # `tree_sitter.Language`. Using `get_parser` directly side-steps that.
    from tree_sitter_language_pack import get_parser as _get_parser  # pyright: ignore[reportMissingImports]

    return _get_parser(language)


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

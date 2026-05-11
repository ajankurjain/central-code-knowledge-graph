"""Shared tree-sitter loader.

Uses tree-sitter-language-pack so we don't have to compile grammars manually.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=32)
def get_ts_parser(language: str):
    """Return a parser with a callable ``.parse(bytes) -> Tree``.

    We try two paths and validate the result, because the relationship
    between ``tree-sitter`` and ``tree-sitter-language-pack`` shifted
    between versions and at least one combination returns a Parser
    object that lacks a usable ``.parse`` method.

    Order:
      1. ``tree_sitter_language_pack.get_parser(name)`` — preferred; one call.
      2. ``tree_sitter.Parser(get_language(name))`` (>=0.23 constructor form)
         falling back to ``Parser(); p.language = lang`` for older bindings.

    If neither path yields a parser with a callable ``.parse``, raise
    ``ImportError`` so the registry's per-language ``try/except`` cleanly
    drops this one language rather than taking the whole loader down.
    """
    last_err: Exception | None = None

    # Path 1: language-pack's own get_parser
    try:
        from tree_sitter_language_pack import (
            get_parser as _get_parser,  # pyright: ignore[reportMissingImports]
        )

        p = _get_parser(language)
        if callable(getattr(p, "parse", None)):
            return p
    except Exception as e:
        last_err = e

    # Path 2: explicit Parser construction
    try:
        from tree_sitter import Parser as TSParser
        from tree_sitter_language_pack import (
            get_language,  # pyright: ignore[reportMissingImports]
        )

        lang = get_language(language)
        try:
            p = TSParser(lang)  # tree-sitter ≥0.23 constructor form
        except Exception:
            p = TSParser()
            p.language = lang  # tree-sitter <0.23 attribute form
        if callable(getattr(p, "parse", None)):
            return p
    except Exception as e:
        last_err = e

    raise ImportError(
        f"no working tree-sitter parser for {language!r}: {last_err}"
    )


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

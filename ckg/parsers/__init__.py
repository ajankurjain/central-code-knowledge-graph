"""Language parsers using Tree-sitter.

Each parser turns a source file into a `ParseResult` of nodes and edges
that the ingest pipeline writes to Neo4j.
"""

from ckg.parsers.base import Parser, ParseResult, get_parser

__all__ = ["ParseResult", "Parser", "get_parser"]

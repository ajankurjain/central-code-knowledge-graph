"""Parser base classes + language dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class FunctionNode:
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    is_method: bool = False
    is_async: bool = False
    doc: str = ""
    body: str = ""        # raw source — used to compute embedding
    body_sha: str = ""
    class_qname: str | None = None  # the enclosing class qname if is_method


@dataclass
class ClassNode:
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    doc: str = ""


@dataclass
class ImportEdge:
    module: str           # e.g. "os.path"
    alias: str | None = None
    is_relative: bool = False


@dataclass
class CallEdge:
    caller_qname: str     # qualified_name of the calling function
    callee_name: str      # raw name as written at the call site
    line: int


@dataclass
class ParseResult:
    path: str
    language: str
    size_bytes: int
    classes: list[ClassNode] = field(default_factory=list)
    functions: list[FunctionNode] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)
    calls: list[CallEdge] = field(default_factory=list)


class Parser(Protocol):
    language: str
    extensions: tuple[str, ...]

    def parse(self, path: Path, source: bytes) -> ParseResult: ...


_REGISTRY: dict[str, Parser] = {}


def register_parser(parser: Parser) -> None:
    _REGISTRY[parser.language] = parser


def get_parser(language: str) -> Parser | None:
    return _REGISTRY.get(language)


def detect_language(path: Path) -> str | None:
    suf = path.suffix.lower()
    for p in _REGISTRY.values():
        if suf in p.extensions:
            return p.language
    return None


def all_languages() -> list[str]:
    return list(_REGISTRY)


# Eager-load known parsers so the registry is populated on import
def _init_registry() -> None:
    # Import side effects register each parser
    from ckg.parsers import python as _py  # noqa: F401
    from ckg.parsers import javascript as _js  # noqa: F401
    from ckg.parsers import rust as _rs  # noqa: F401
    from ckg.parsers import go as _go  # noqa: F401
    from ckg.parsers import java as _ja  # noqa: F401
    from ckg.parsers import ruby as _rb  # noqa: F401


_init_registry()

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
    line: int             # 1-based
    character: int = 0    # 0-based column of the callee identifier — used by the LSP pass


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
    # Import side effects register each parser. Wrap in try/except per language
    # so a missing grammar in `tree-sitter-language-pack` only drops that
    # language, not the whole loader.
    for modname in (
        "python", "javascript", "rust", "go", "java", "ruby", "c", "cpp",
        "csharp", "kotlin", "scala", "swift", "php", "solidity", "dart",
        "r", "perl", "lua", "zig", "powershell", "julia", "nix",
        "vue", "svelte", "ipynb",
    ):
        try:
            __import__(f"ckg.parsers.{modname}")
        except Exception:
            # Grammar missing or parser self-test failed — skip silently.
            # The registry simply won't list this language; ingest will
            # treat files of that extension as unsupported.
            pass


_init_registry()

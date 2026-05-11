"""LSP adapter protocol + shared types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ResolvedLocation:
    """The definition site of a symbol, as returned by `textDocument/definition`."""

    file_path: str        # relative to repo root
    line: int             # 1-based to match our graph
    character: int        # 0-based column


class LspAdapter(Protocol):
    """One adapter per language. Each adapter knows how to launch its language
    server and (optionally) preconfigure it for a given repo root."""

    language: str         # matches ParseResult.language (e.g. "python")

    def is_available(self) -> bool:
        """True if the LSP binary is on PATH."""
        ...

    def server_command(self, repo_root: Path) -> list[str]:
        """The command to spawn; the generic client opens stdio to it."""
        ...

    def file_uri_extensions(self) -> tuple[str, ...]:
        """File extensions this adapter handles (e.g. ('.py',))."""
        ...

    def language_id(self) -> str:
        """The LSP `languageId` string for this language (e.g. 'python')."""
        ...

    def initialization_options(self) -> dict | None:
        """Optional initializationOptions sent to the server. Default None."""
        ...

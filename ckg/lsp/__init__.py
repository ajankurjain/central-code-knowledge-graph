"""Opt-in LSP precision pass.

When enabled (`CKG_LSP_ENABLED=true`), after the tree-sitter ingest the
pipeline talks to each available language server to resolve cross-file
call edges precisely — pyright for Python today, rust-analyzer / gopls /
ts-server / jdtls planned.

LSPs are NOT required for the graph to work. The name-based resolver
always runs; the LSP pass only **upgrades** edges it can locate
precisely, tagging them with `precise: true`. Calls the LSP can't
resolve (or files in languages with no adapter installed) keep the
name-match fallback.
"""

from ckg.lsp.base import LspAdapter, ResolvedLocation
from ckg.lsp.registry import available_adapters, get_adapter

__all__ = ["LspAdapter", "ResolvedLocation", "available_adapters", "get_adapter"]

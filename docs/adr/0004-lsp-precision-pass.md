# ADR 0004 — Opt-in LSP precision pass for cross-file call resolution

**Status**: Accepted (Phase 3, alpha)
**Date**: 2026-05-11

## Context

Tree-sitter call sites only know the **short name** of the callee — `format(...)`
gives us `"format"`, not `module_a.format` vs `module_b.format`. The Phase 1
resolver matches on short name across the entire repo, which produces both
false positives (every `format` matches every `format`) and false negatives
(`from x import format as f; f()` is missed).

Language servers solve exactly this problem — `textDocument/definition`
returns a precise `(file, line, character)` for the symbol under the cursor.

## Decision

Add an **opt-in** LSP pass that runs after the name-based resolver and
**upgrades** edges to precise ones. The graph still works without any LSP
installed; the LSP pass tags resolved edges with `precise: true` so
queries can prefer them.

Module layout:

```
ckg/lsp/
├── base.py        # LspAdapter protocol, ResolvedLocation dataclass
├── client.py      # generic JSON-RPC over stdio (initialize, didOpen,
│                  # textDocument/definition, shutdown — enough to drive
│                  # a definition lookup loop)
├── pyright.py     # pyright-langserver adapter for Python
└── registry.py    # language → adapter class
ckg/services/lsp_resolve.py   # the pass itself, called from ingest_repo
```

### Flow

1. After ingest writes CallSites and the name-based resolver creates
   coarse CALLS edges.
2. For each language with an available adapter:
   1. Spawn one LSP server, scoped to the repo root.
   2. Pull all CallSites for files of that language (file/line/character).
   3. Group by file, `didOpen` each file, send one `textDocument/definition`
      per call site, then `didClose`.
   4. For each resolved Location inside the repo, find the Function whose
      `[start_line, end_line]` brackets the target line in the target file
      (smallest match wins to handle nested defs) and `MERGE` a
      `(:Function)-[:CALLS {precise: true, line}]->(target)` edge.
3. Shutdown each LSP.

### Config

- `CKG_LSP_ENABLED=false` by default — turn on after installing the LSP binaries.
- `CKG_LSP_ADAPTERS=` (CSV; empty = run every available adapter).

### Adapter API

```python
class LspAdapter(Protocol):
    language: str
    def is_available(self) -> bool: ...
    def server_command(self, repo_root: Path) -> list[str]: ...
    def file_uri_extensions(self) -> tuple[str, ...]: ...
    def language_id(self) -> str: ...
    def initialization_options(self) -> dict | None: ...
```

Today: `PyrightAdapter` (Python). Stubs planned for rust-analyzer, gopls,
ts-server, jdtls.

## Consequences

Good:
- Removes Phase 1's name-collision false-positives without changing the
  graph schema.
- Each language is an independent adapter; missing binaries are a no-op,
  not a failure.
- The name-based fallback stays in place — the LSP pass only adds
  precision where it can.

Tradeoffs:
- LSPs are slow on cold start. Pyright on a ~10 kfile repo: 30–90 s index
  + ~5 ms per definition. The Cypher upgrade dominates on small repos; the
  LSP indexing dominates on large ones.
- We send one definition request per call site. Future optimization: batch
  by file using `documentSymbol` to find local definitions first.
- We pick the first Location returned by the server (some servers return
  multiple — e.g. for overloads). Phase 3+ should rank these.

## Open work

- Rust-analyzer, gopls, ts-server, jdtls adapters.
- Concurrent multi-language LSP execution (currently sequential).
- Persist `precise` flag in the GraphQL `FunctionRef` type so consumers
  can sort or filter.

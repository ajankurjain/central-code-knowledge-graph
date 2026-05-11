# ADR 0009 — Broad language support (23 + 3 wrappers)

**Status**: Accepted
**Date**: 2026-05-11

## Context

Phase 1–3 covered 9 languages (Python, JS/TS, Rust, Go, Java, Ruby, C,
C++). Real-world polyglot orgs want every meaningful language in the
graph — the user's ask was: Python, TypeScript/TSX, JavaScript, Vue,
Svelte, Go, Rust, Java, Scala, C#, Ruby, Kotlin, Swift, PHP, Solidity,
C/C++, Dart, R, Perl, Lua, Zig, PowerShell, Julia, Nix, Angular, React,
Jupyter/Databricks (.ipynb).

## Decision

Implement 14 new tree-sitter parsers, 3 extraction wrappers, and
explicitly document the two frameworks-not-languages cases.

### Tree-sitter parsers (23 total)

| Language | File | Notes |
|---|---|---|
| Python | `python.py` | Phase 1 |
| JavaScript / TypeScript (incl. JSX/TSX) | `javascript.py` | Phase 1; one parser covers JS, JSX, TS, TSX |
| Rust | `rust.py` | Phase 2; `impl` blocks → method routing |
| Go | `go.py` | Phase 2; receiver type → method routing |
| Java | `java.py` | Phase 2; package + nested classes |
| Ruby | `ruby.py` | Phase 2 |
| C | `c.py` | Phase 3 |
| C++ | `cpp.py` | Phase 3; namespaces + qualified_identifier methods |
| C# | `csharp.py` | namespace / using / class+interface+struct+record+enum / method+ctor+dtor |
| Kotlin | `kotlin.py` | package_header / import_header / class/object/interface / suspend → async |
| Scala | `scala.py` | package_clause / class+object+trait / template_body walks |
| Swift | `swift.py` | class/struct/protocol/extension/enum / init/deinit / async |
| PHP | `php.py` | namespace + use / class+interface+trait+enum / member+scoped+new calls |
| Solidity | `solidity.py` | contract/interface/library / modifier / constructor / fallback/receive |
| Dart | `dart.py` | class/mixin/extension/enum / function_signature → body resolution |
| R | `r.py` | `name <- function(...)` assignments / library/require/source imports |
| Perl | `perl.py` | subroutine_declaration / use/require/no |
| Lua | `lua.py` | function declarations / local functions / `require()` imports |
| Zig | `zig.py` | `fn_decl` / `const X = struct {…}` / `@import("…")` |
| PowerShell | `powershell.py` | function_statement / `Import-Module` / `using` |
| Julia | `julia.py` | function/short_function/macro / using+import / module nesting |
| Nix | `nix.py` | function-typed bindings / `import` expressions / call apply |

Each parser implements the same `Parser` protocol; shared boilerplate
(emit_class, emit_function, collect_calls, trailing_name,
module_qname_from_path) lives in `ckg/parsers/_generic.py`.

### Extraction wrappers (3)

`.vue`, `.svelte`, `.ipynb` aren't single-language tree-sitter targets —
they're container formats. We treat them as such:

- **Vue / Svelte SFCs** — regex out the `<script[ lang=ts]>...</script>`
  block, dispatch its contents to the JS/TS parser using a virtual
  `.ts/.js` filename, then re-base the reported line numbers by the
  script block's line offset in the SFC.
- **Jupyter / Databricks `.ipynb`** — parse as JSON. Look up the kernel
  language at `metadata.kernelspec.language`. Concatenate every
  `cell_type == "code"` cell's `source` (preserving non-code-cell line
  heights so line numbers track the visible notebook), dispatch the
  synthetic source to the matching language parser, and label the
  result as `ipynb/<lang>` so downstream queries can filter.

### Frameworks (not languages)

- **Angular** — TypeScript + HTML templates. The TypeScript half is
  already covered by `javascript.py`'s `.ts/.tsx` handling. Template
  HTML isn't indexed; that's a future enhancement.
- **React** — JSX/TSX. Already covered by `javascript.py`.

## Loader robustness

`base.py::_init_registry` now imports each parser inside a `try/except`.
A missing grammar in `tree-sitter-language-pack` drops that one language
silently; the rest of the registry stays healthy.

## Consequences

Good:
- Single-source-of-truth registry — drop a new parser file, add a line,
  done.
- Wrappers reuse existing parsers, so they pick up improvements
  automatically (e.g. when LSP coverage broadens, Vue/Svelte
  `<script>` blocks gain precision for free).
- Try/except loader keeps the system bootable in restricted
  environments where some grammars aren't shipped.

Tradeoffs:
- The 14 new parsers are written from grammar conventions, not against
  real-world repos in this environment. Some are likely to need
  refinement once exercised — particularly Julia (multiple-dispatch
  syntax), R (dynamic assignment patterns), and Nix (highly
  expression-oriented). The defensive coding keeps them from
  crashing; precision can be tuned per ticket.
- Vue/Svelte script extraction uses a regex rather than the
  tree-sitter vue/svelte grammar. That's correct for the SFC structural
  case but doesn't catch `<script context="module">` doubling or other
  edge cases. Acceptable for v1; the dedicated grammars can replace
  this later.
- `.ipynb` cell concatenation discards markdown / output cells. A real
  notebook explorer would surface them as separate entities; we don't
  need that for the call/import graph.

"""R parser via tree-sitter.

R is dynamic and dispatch-based — there are no real "classes" in the
language sense. We extract:

- function assignments at top level / in libraries  (e.g. `foo <- function(...) ...`)
- `library(pkg)`, `require(pkg)` calls as imports
- call expressions inside function bodies as call edges
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ckg.parsers._generic import (
    collect_calls,
    emit_function,
    module_qname_from_path,
    trailing_name,
)
from ckg.parsers._ts import get_ts_parser, node_text
from ckg.parsers.base import CallEdge, ImportEdge, ParseResult, register_parser

_IMPORT_CALLS = {"library", "require", "requireNamespace", "loadNamespace", "source"}
_CALL_TYPES = {"call"}


@dataclass
class RParser:
    language: str = "r"
    extensions: tuple[str, ...] = (".r", ".R", ".Rmd")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("r")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="r", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, result)
        return result


def _walk(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "left_assignment" or n.type == "equals_assignment":
            # name <- function(...) {...}
            lhs = n.child_by_field_name("name") or n.named_children[0] if n.named_child_count else None
            rhs = n.child_by_field_name("value") or (n.named_children[-1] if n.named_child_count else None)
            if rhs is not None and rhs.type in ("function_definition", "function_literal"):
                name = node_text(source, lhs) if lhs is not None else "?"
                fn_qname = emit_function(
                    node=n, source=source, name=name,
                    module_qname=module_qname, parents=[], sep=".",
                    is_method=False, is_async=False,
                    functions_out=result.functions,
                )
                body = rhs.child_by_field_name("body") or _last_named(rhs)
                if body is not None:
                    collect_calls(
                        body=body, source=source, caller_qname=fn_qname,
                        call_node_types=_CALL_TYPES, name_extractor=_call_name,
                        calls_out=result.calls,
                    )
                continue
        elif n.type == "call":
            # Top-level library() / require() — record as import
            fn = n.child_by_field_name("function") or _first_named(n)
            if fn is not None and fn.type == "identifier":
                name = node_text(source, fn)
                if name in _IMPORT_CALLS:
                    args = n.child_by_field_name("arguments") or _last_named(n)
                    if args is not None:
                        for g in args.named_children:
                            if g.type in ("identifier", "string", "string_literal"):
                                result.imports.append(ImportEdge(module=node_text(source, g).strip("\"'")))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


def _last_named(n):
    return n.named_children[-1] if n.named_child_count > 0 else None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


# Silence unused-import warning when CallEdge isn't referenced directly.
_ = CallEdge

register_parser(RParser())

"""Nix parser via tree-sitter.

Nix is expression-oriented and lambda-based — no "functions" or "classes"
in the imperative sense. We surface a couple of useful structures so
graph queries still return something:

- top-level bindings whose value is a function (`pkgs.lib.foo = arg: ...`)
- `import <path>` / `import ./relative.nix` expressions as imports
- direct function applications inside lambdas as call edges (best-effort)
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
from ckg.parsers.base import ImportEdge, ParseResult, register_parser

_CALL_TYPES = {"apply_expression", "application"}


@dataclass
class NixParser:
    language: str = "nix"
    extensions: tuple[str, ...] = (".nix",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("nix")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="nix", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, result)
        return result


def _walk(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in ("binding", "inherit_attrset"):
            attrpath = n.child_by_field_name("attrpath") or _first_named(n)
            value = n.child_by_field_name("expression") or _last_named(n)
            if attrpath is not None and value is not None and value.type in ("function_expression", "function"):
                name = node_text(source, attrpath)
                fn_qname = emit_function(
                    node=n, source=source, name=name,
                    module_qname=module_qname, parents=[], sep=".",
                    is_method=False, is_async=False,
                    functions_out=result.functions,
                )
                body = value.child_by_field_name("body") or _last_named(value)
                if body is not None:
                    collect_calls(
                        body=body, source=source, caller_qname=fn_qname,
                        call_node_types=_CALL_TYPES, name_extractor=_call_name,
                        calls_out=result.calls,
                    )
        elif n.type in ("apply_expression", "application"):
            # `import <path>` / `import ./foo.nix`
            head = n.child_by_field_name("function") or _first_named(n)
            arg = n.child_by_field_name("argument") or _last_named(n)
            if (
                head is not None
                and head.type == "identifier"
                and node_text(source, head) == "import"
                and arg is not None
            ):
                txt = node_text(source, arg).strip()
                result.imports.append(ImportEdge(module=txt.strip("<>'\""), is_relative=txt.startswith(".")))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


def _last_named(n):
    return n.named_children[-1] if n.named_child_count > 0 else None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


register_parser(NixParser())

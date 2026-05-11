"""Zig parser via tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ckg.parsers._generic import (
    collect_calls,
    emit_class,
    emit_function,
    module_qname_from_path,
    trailing_name,
)
from ckg.parsers._ts import get_ts_parser, node_text
from ckg.parsers.base import ImportEdge, ParseResult, register_parser

_CALL_TYPES = {"call_expression"}


@dataclass
class ZigParser:
    language: str = "zig"
    extensions: tuple[str, ...] = (".zig",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("zig")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="zig", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "variable_declaration":
            # const T = struct {...} or const X = @import("...")
            init = n.child_by_field_name("value") or _last_named(n)
            if init is not None:
                if init.type in ("struct_declaration", "enum_declaration", "union_declaration"):
                    name_node = n.child_by_field_name("name") or _first_id(n)
                    name = node_text(source, name_node) if name_node is not None else "?"
                    emit_class(
                        node=init, name=name, module_qname=module_qname,
                        parents=parents, sep=".", classes_out=result.classes,
                    )
                elif init.type == "builtin_function":
                    bname = init.child_by_field_name("name") or _first_id(init)
                    if bname is not None and node_text(source, bname) in ("@import", "import"):
                        args = init.child_by_field_name("arguments") or _last_named(init)
                        if args is not None:
                            for g in args.named_children:
                                if g.type in ("string", "string_literal"):
                                    result.imports.append(ImportEdge(module=node_text(source, g).strip("\"'")))
                                    break
        elif n.type in ("function_declaration", "fn_decl"):
            name_node = n.child_by_field_name("name") or _first_id(n)
            name = node_text(source, name_node) if name_node is not None else "?"
            fn_qname = emit_function(
                node=n, source=source, name=name,
                module_qname=module_qname, parents=parents, sep=".",
                is_method=False, is_async=False,
                functions_out=result.functions,
            )
            body = n.child_by_field_name("body") or _first_block(n)
            if body is not None:
                collect_calls(
                    body=body, source=source, caller_qname=fn_qname,
                    call_node_types=_CALL_TYPES, name_extractor=_call_name,
                    calls_out=result.calls,
                )
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _first_id(n):
    for c in n.named_children:
        if c.type == "identifier":
            return c
    return None


def _first_block(n):
    for c in n.children:
        if c.type in ("block",):
            return c
    return None


def _last_named(n):
    return n.named_children[-1] if n.named_child_count > 0 else None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(ZigParser())

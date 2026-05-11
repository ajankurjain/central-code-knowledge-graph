"""C parser via tree-sitter.

Headers (.h) are ambiguous between C and C++; we default to C and let
.hpp/.hxx/.hh route to the C++ parser.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ckg.parsers._ts import get_ts_parser, node_text
from ckg.parsers.base import (
    CallEdge,
    ClassNode,
    FunctionNode,
    ImportEdge,
    ParseResult,
    register_parser,
)


@dataclass
class CParser:
    language: str = "c"
    extensions: tuple[str, ...] = (".c", ".h")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("c")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="c", size_bytes=len(source))
        module_qname = _module_qname(path)
        _walk(tree.root_node, source, module_qname, result)
        return result


def _module_qname(path: Path) -> str:
    return "::".join(path.with_suffix("").parts)


def _walk(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "preproc_include":
            inc = child.child_by_field_name("path")
            if inc is not None:
                mod = node_text(source, inc).strip("\"<>")
                result.imports.append(ImportEdge(
                    module=mod,
                    is_relative=node_text(source, inc).startswith("\""),
                ))
        elif t in ("struct_specifier", "union_specifier", "enum_specifier"):
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                name = node_text(source, name_node)
                result.classes.append(ClassNode(
                    name=name,
                    qualified_name=f"{module_qname}::{name}",
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                ))
        elif t == "function_definition":
            _emit_function(child, source, module_qname, result)
        elif t == "linkage_specification":
            # extern "C" { ... } in C++-flavoured headers
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, result)


def _emit_function(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    declarator = node.child_by_field_name("declarator")
    name = _function_name(declarator, source) if declarator is not None else "?"
    qname = f"{module_qname}::{name}"
    body_text = node_text(source, node)
    fn = FunctionNode(
        name=name, qualified_name=qname,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        is_method=False,
        is_async=False,
        body=body_text,
        body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
    )
    result.functions.append(fn)
    body = node.child_by_field_name("body")
    if body is not None:
        _collect_calls(body, source, fn.qualified_name, result)


def _function_name(declarator, source: bytes) -> str:
    """Walk pointer/function declarators to find the identifier."""
    n = declarator
    while n is not None:
        if n.type == "identifier":
            return node_text(source, n)
        if n.type == "function_declarator":
            n = n.child_by_field_name("declarator")
            continue
        if n.type == "pointer_declarator":
            n = n.child_by_field_name("declarator")
            continue
        if n.type == "parenthesized_declarator" and n.named_child_count > 0:
            n = n.named_children[0]
            continue
        # any other declarator kind we don't recognise — bail
        return ""
    return ""


def _collect_calls(body, source: bytes, caller_qname: str, result: ParseResult) -> None:
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            fn_node = n.child_by_field_name("function")
            if fn_node is not None:
                callee = _call_target(fn_node, source)
                if callee:
                    result.calls.append(CallEdge(
                        caller_qname=caller_qname,
                        callee_name=callee,
                        line=n.start_point[0] + 1,
                    ))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _call_target(fn_node, source: bytes) -> str:
    if fn_node.type == "identifier":
        return node_text(source, fn_node)
    if fn_node.type == "field_expression":
        field = fn_node.child_by_field_name("field")
        return node_text(source, field) if field is not None else ""
    if fn_node.type == "parenthesized_expression" and fn_node.named_child_count > 0:
        return _call_target(fn_node.named_children[0], source)
    return ""


register_parser(CParser())

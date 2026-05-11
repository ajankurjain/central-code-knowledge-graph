"""Go parser via tree-sitter."""

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
class GoParser:
    language: str = "go"
    extensions: tuple[str, ...] = (".go",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("go")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="go", size_bytes=len(source))
        module_qname = _module_qname(path)
        _walk(tree.root_node, source, module_qname, result)
        return result


def _module_qname(path: Path) -> str:
    return ".".join(path.with_suffix("").parts)


def _walk(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "import_declaration":
            for imp in _imports(child, source):
                result.imports.append(imp)
        elif t == "type_declaration":
            for spec in child.named_children:
                if spec.type == "type_spec":
                    name_node = spec.child_by_field_name("name")
                    name = node_text(source, name_node) if name_node is not None else "?"
                    result.classes.append(ClassNode(
                        name=name,
                        qualified_name=f"{module_qname}.{name}",
                        start_line=spec.start_point[0] + 1,
                        end_line=spec.end_point[0] + 1,
                    ))
        elif t == "function_declaration":
            _emit_function(child, source, module_qname, result, receiver_qname=None)
        elif t == "method_declaration":
            recv_qname = _receiver_qname(child, source, module_qname)
            _emit_function(child, source, module_qname, result, receiver_qname=recv_qname)


def _imports(node, source: bytes) -> list[ImportEdge]:
    out: list[ImportEdge] = []
    for c in node.named_children:
        if c.type == "import_spec":
            path_node = c.child_by_field_name("path")
            alias_node = c.child_by_field_name("name")
            if path_node is not None:
                mod = node_text(source, path_node).strip('"`')
                alias = node_text(source, alias_node) if alias_node is not None else None
                out.append(ImportEdge(module=mod, alias=alias))
        elif c.type == "import_spec_list":
            for spec in c.named_children:
                if spec.type == "import_spec":
                    path_node = spec.child_by_field_name("path")
                    alias_node = spec.child_by_field_name("name")
                    if path_node is not None:
                        mod = node_text(source, path_node).strip('"`')
                        alias = node_text(source, alias_node) if alias_node is not None else None
                        out.append(ImportEdge(module=mod, alias=alias))
    return out


def _receiver_qname(method_node, source: bytes, module_qname: str) -> str | None:
    recv = method_node.child_by_field_name("receiver")
    if recv is None:
        return None
    for c in recv.named_children:
        if c.type == "parameter_declaration":
            ty = c.child_by_field_name("type")
            if ty is not None:
                # *T or T → use T
                txt = node_text(source, ty).lstrip("*")
                return f"{module_qname}.{txt}"
    return None


def _emit_function(node, source: bytes, module_qname: str, result: ParseResult, receiver_qname: str | None) -> None:
    name_node = node.child_by_field_name("name")
    name = node_text(source, name_node) if name_node is not None else "?"
    qname = (f"{receiver_qname}.{name}" if receiver_qname else f"{module_qname}.{name}")
    body_text = node_text(source, node)
    fn = FunctionNode(
        name=name, qualified_name=qname,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        is_method=receiver_qname is not None,
        is_async=False,
        body=body_text,
        body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
        class_qname=receiver_qname,
    )
    result.functions.append(fn)
    body = node.child_by_field_name("body")
    if body is not None:
        _collect_calls(body, source, fn.qualified_name, result)


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
    if fn_node.type == "selector_expression":
        field = fn_node.child_by_field_name("field")
        return node_text(source, field) if field is not None else ""
    return ""


register_parser(GoParser())

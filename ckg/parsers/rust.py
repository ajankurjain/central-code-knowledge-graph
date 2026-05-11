"""Rust parser via tree-sitter."""

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
class RustParser:
    language: str = "rust"
    extensions: tuple[str, ...] = (".rs",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("rust")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="rust", size_bytes=len(source))
        module_qname = _module_qname(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _module_qname(path: Path) -> str:
    # crate::path::module — approximate using on-disk relative path
    parts = list(path.with_suffix("").parts)
    return "::".join(p for p in parts if p and p not in (".", "/", "src"))


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "use_declaration":
            for imp in _imports(child, source):
                result.imports.append(imp)
        elif t in ("struct_item", "enum_item", "trait_item", "union_item"):
            name = _ident(child.child_by_field_name("name"), source)
            qname = "::".join([module_qname, *parents, name]) if name else module_qname
            result.classes.append(ClassNode(
                name=name or "?", qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
            ))
        elif t == "impl_item":
            # methods inside an impl block — record the type as a "class" context
            ty_node = child.child_by_field_name("type")
            ty = node_text(source, ty_node) if ty_node is not None else "?"
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, parents + [ty], result)
        elif t == "function_item":
            name = _ident(child.child_by_field_name("name"), source)
            qname = "::".join([module_qname, *parents, name])
            body_text = node_text(source, child)
            is_method = bool(parents)
            fn = FunctionNode(
                name=name or "?", qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                is_method=is_method,
                is_async=_has_async(child),
                body=body_text,
                body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
                class_qname="::".join([module_qname, *parents]) if is_method else None,
            )
            result.functions.append(fn)
            body = child.child_by_field_name("body")
            if body is not None:
                _collect_calls(body, source, fn.qualified_name, result)
        elif t == "mod_item":
            name = _ident(child.child_by_field_name("name"), source)
            body = child.child_by_field_name("body")
            if body is not None and name:
                _walk(body, source, module_qname, parents + [name], result)
        else:
            _walk(child, source, module_qname, parents, result)


def _ident(node, source: bytes) -> str:
    return node_text(source, node) if node is not None else ""


def _has_async(node) -> bool:
    for c in node.children:
        if c.type == "function_modifiers":
            for m in c.children:
                if m.type == "async":
                    return True
        if c.type == "async":
            return True
    return False


def _imports(node, source: bytes) -> list[ImportEdge]:
    """Flatten use-tree into one ImportEdge per leaf path."""
    out: list[ImportEdge] = []
    body = None
    for c in node.children:
        if c.type in ("scoped_use_list", "use_list", "use_as_clause", "scoped_identifier", "identifier", "self", "use_wildcard"):
            body = c
            break
    if body is None:
        return out

    def add_path(path: str, alias: str | None = None) -> None:
        out.append(ImportEdge(module=path, alias=alias))

    def walk(n, prefix: list[str]) -> None:
        if n.type == "identifier":
            add_path("::".join(prefix + [node_text(source, n)]))
        elif n.type == "scoped_identifier":
            txt = node_text(source, n)
            add_path("::".join(prefix + [txt]))
        elif n.type == "use_as_clause":
            inner = n.child_by_field_name("path")
            alias_node = n.child_by_field_name("alias")
            if inner is not None:
                add_path(node_text(source, inner), alias=node_text(source, alias_node) if alias_node else None)
        elif n.type == "scoped_use_list":
            inner_prefix_node = n.child_by_field_name("path")
            inner_prefix = node_text(source, inner_prefix_node).split("::") if inner_prefix_node is not None else []
            for grand in n.named_children:
                if grand is inner_prefix_node:
                    continue
                walk(grand, prefix + inner_prefix)
        elif n.type == "use_list":
            for grand in n.named_children:
                walk(grand, prefix)
        else:
            # Generic fallback: use the raw text as a single import
            add_path(node_text(source, n))

    walk(body, [])
    return out


def _collect_calls(body, source: bytes, caller_qname: str, result: ParseResult) -> None:
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type in ("call_expression", "macro_invocation"):
            fn_node = n.child_by_field_name("function") if n.type == "call_expression" else n.child_by_field_name("macro")
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
    if fn_node.type == "scoped_identifier":
        # e.g. ns::foo  → use the trailing name
        name = fn_node.child_by_field_name("name")
        return node_text(source, name) if name is not None else ""
    return ""


register_parser(RustParser())

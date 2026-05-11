"""Java parser via tree-sitter."""

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
class JavaParser:
    language: str = "java"
    extensions: tuple[str, ...] = (".java",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("java")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="java", size_bytes=len(source))
        # The package declaration gives us the qualified-name prefix.
        pkg = _package(tree.root_node, source)
        _walk(tree.root_node, source, pkg, parents=[], result=result)
        return result


def _package(root, source: bytes) -> str:
    for c in root.children:
        if c.type == "package_declaration":
            for grand in c.named_children:
                if grand.type in ("scoped_identifier", "identifier"):
                    return node_text(source, grand)
    # fall back to file basename
    return ""


def _walk(node, source: bytes, pkg: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "import_declaration":
            for grand in child.named_children:
                if grand.type in ("scoped_identifier", "identifier"):
                    result.imports.append(ImportEdge(module=node_text(source, grand)))
        elif t in ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration"):
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "?"
            qname_parts = [p for p in [pkg, *parents, name] if p]
            qname = ".".join(qname_parts)
            result.classes.append(ClassNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
            ))
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, pkg, parents + [name], result)
        elif t in ("method_declaration", "constructor_declaration"):
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "?"
            qname_parts = [p for p in [pkg, *parents, name] if p]
            qname = ".".join(qname_parts)
            body_text = node_text(source, child)
            class_qname = ".".join(p for p in [pkg, *parents] if p) if parents else None
            fn = FunctionNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                is_method=bool(parents),
                is_async=False,
                body=body_text,
                body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
                class_qname=class_qname,
            )
            result.functions.append(fn)
            body = child.child_by_field_name("body")
            if body is not None:
                _collect_calls(body, source, fn.qualified_name, result)
        else:
            _walk(child, source, pkg, parents, result)


def _collect_calls(body, source: bytes, caller_qname: str, result: ParseResult) -> None:
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "method_invocation":
            name_node = n.child_by_field_name("name")
            if name_node is not None:
                result.calls.append(CallEdge(
                    caller_qname=caller_qname,
                    callee_name=node_text(source, name_node),
                    line=n.start_point[0] + 1,
                ))
        elif n.type == "object_creation_expression":
            ty = n.child_by_field_name("type")
            if ty is not None:
                result.calls.append(CallEdge(
                    caller_qname=caller_qname,
                    callee_name=node_text(source, ty),
                    line=n.start_point[0] + 1,
                ))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


register_parser(JavaParser())

"""Kotlin parser via tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ckg.parsers._generic import (
    collect_calls,
    emit_class,
    emit_function,
    field_text,
    module_qname_from_path,
    trailing_name,
)
from ckg.parsers._ts import get_ts_parser, node_text
from ckg.parsers.base import ImportEdge, ParseResult, register_parser

_CALL_TYPES = {"call_expression"}


@dataclass
class KotlinParser:
    language: str = "kotlin"
    extensions: tuple[str, ...] = (".kt", ".kts")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("kotlin")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="kotlin", size_bytes=len(source))
        pkg = _package(tree.root_node, source) or module_qname_from_path(path)
        _walk(tree.root_node, source, pkg, parents=[], result=result)
        return result


def _package(root, source: bytes) -> str:
    for c in root.children:
        if c.type == "package_header":
            for g in c.named_children:
                if g.type in ("identifier", "simple_identifier", "qualified_name"):
                    return node_text(source, g)
    return ""


def _walk(node, source: bytes, pkg: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "import_header":
            for g in child.named_children:
                if g.type in ("identifier", "qualified_name"):
                    result.imports.append(ImportEdge(module=node_text(source, g)))
        elif t in ("class_declaration", "object_declaration", "interface_declaration"):
            name = field_text(child, source, "name") or _ident_child(child, source) or "?"
            emit_class(
                node=child, name=name, module_qname=pkg, parents=parents,
                sep=".", classes_out=result.classes,
            )
            body = child.child_by_field_name("body") or _first_block(child)
            if body is not None:
                _walk(body, source, pkg, [*parents, name], result)
        elif t == "function_declaration":
            name = field_text(child, source, "name") or _ident_child(child, source) or "?"
            is_method = bool(parents)
            class_qname = ".".join(p for p in [pkg, *parents] if p) if parents else None
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=pkg, parents=parents, sep=".",
                is_method=is_method, is_async=_has_modifier(child, "suspend"),
                functions_out=result.functions, class_qname=class_qname,
            )
            body = child.child_by_field_name("body") or _first_block(child)
            if body is not None:
                collect_calls(
                    body=body, source=source, caller_qname=fn_qname,
                    call_node_types=_CALL_TYPES, name_extractor=_call_name,
                    calls_out=result.calls,
                )
        else:
            _walk(child, source, pkg, parents, result)


def _ident_child(node, source: bytes) -> str:
    for c in node.named_children:
        if c.type in ("simple_identifier", "identifier", "type_identifier"):
            return node_text(source, c)
    return ""


def _first_block(node):
    for c in node.children:
        if c.type in ("function_body", "class_body", "block", "enum_class_body"):
            return c
    return None


def _has_modifier(node, name: str) -> bool:
    for c in node.children:
        if c.type == "modifiers":
            for m in c.children:
                if m.type == name or any(g.type == name for g in m.children):
                    return True
    return False


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("expression") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(KotlinParser())

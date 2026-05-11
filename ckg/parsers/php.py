"""PHP parser via tree-sitter."""

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

_CALL_TYPES = {"function_call_expression", "member_call_expression", "scoped_call_expression", "object_creation_expression"}


@dataclass
class PhpParser:
    language: str = "php"
    extensions: tuple[str, ...] = (".php", ".phtml")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("php")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="php", size_bytes=len(source))
        ns = _namespace(tree.root_node, source) or module_qname_from_path(path, sep="\\")
        _walk(tree.root_node, source, ns, parents=[], result=result)
        return result


def _namespace(root, source: bytes) -> str:
    for c in root.children:
        if c.type == "namespace_definition":
            n = c.child_by_field_name("name")
            if n is not None:
                return node_text(source, n)
    return ""


def _walk(node, source: bytes, ns: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t in ("namespace_use_declaration",):
            for g in child.named_children:
                if g.type == "namespace_use_clause":
                    name = g.child_by_field_name("name") or _first_id(g)
                    if name is not None:
                        result.imports.append(ImportEdge(module=node_text(source, name)))
        elif t in ("class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"):
            name = field_text(child, source, "name") or "?"
            emit_class(
                node=child, name=name, module_qname=ns, parents=parents,
                sep="\\", classes_out=result.classes,
            )
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, ns, parents + [name], result)
        elif t in ("method_declaration", "function_definition"):
            name = field_text(child, source, "name") or "?"
            is_method = t == "method_declaration"
            class_qname = "\\".join(p for p in [ns, *parents] if p) if is_method and parents else None
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=ns, parents=parents if is_method else [], sep="\\",
                is_method=is_method, is_async=False,
                functions_out=result.functions, class_qname=class_qname,
            )
            body = child.child_by_field_name("body")
            if body is not None:
                collect_calls(
                    body=body, source=source, caller_qname=fn_qname,
                    call_node_types=_CALL_TYPES, name_extractor=_call_name,
                    calls_out=result.calls,
                )
        else:
            _walk(child, source, ns, parents, result)


def _first_id(n):
    for c in n.named_children:
        if c.type in ("identifier", "name", "qualified_name"):
            return c
    return None


def _call_name(n, source: bytes) -> str:
    if n.type == "function_call_expression":
        fn = n.child_by_field_name("function")
        return trailing_name(fn, source) if fn is not None else ""
    if n.type in ("member_call_expression", "scoped_call_expression"):
        name = n.child_by_field_name("name")
        return node_text(source, name) if name is not None else ""
    if n.type == "object_creation_expression":
        ty = n.child_by_field_name("type") or _first_id(n)
        return trailing_name(ty, source) if ty is not None else ""
    return ""


register_parser(PhpParser())

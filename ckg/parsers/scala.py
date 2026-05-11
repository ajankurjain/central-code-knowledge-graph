"""Scala parser via tree-sitter."""

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
_CLASS_TYPES = {"class_definition", "object_definition", "trait_definition", "enum_definition"}
_FN_TYPES = {"function_definition", "function_declaration"}


@dataclass
class ScalaParser:
    language: str = "scala"
    extensions: tuple[str, ...] = (".scala", ".sc")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("scala")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="scala", size_bytes=len(source))
        pkg = _package(tree.root_node, source) or module_qname_from_path(path)
        _walk(tree.root_node, source, pkg, parents=[], result=result)
        return result


def _package(root, source: bytes) -> str:
    for c in root.children:
        if c.type == "package_clause":
            for g in c.named_children:
                if g.type in ("package_identifier", "identifier", "stable_identifier"):
                    return node_text(source, g)
    return ""


def _walk(node, source: bytes, pkg: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "import_declaration":
            for g in child.named_children:
                if g.type in ("import_expression", "stable_identifier", "identifier"):
                    result.imports.append(ImportEdge(module=node_text(source, g)))
        elif t in _CLASS_TYPES:
            name = field_text(child, source, "name") or "?"
            emit_class(
                node=child, name=name, module_qname=pkg, parents=parents,
                sep=".", classes_out=result.classes,
            )
            body = child.child_by_field_name("body") or _template_body(child)
            if body is not None:
                _walk(body, source, pkg, [*parents, name], result)
        elif t in _FN_TYPES:
            name = field_text(child, source, "name") or "?"
            is_method = bool(parents)
            class_qname = ".".join(p for p in [pkg, *parents] if p) if parents else None
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=pkg, parents=parents, sep=".",
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
            _walk(child, source, pkg, parents, result)


def _template_body(node):
    for c in node.children:
        if c.type in ("template_body", "block"):
            return c
    return None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(ScalaParser())

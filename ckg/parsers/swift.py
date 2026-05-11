"""Swift parser via tree-sitter."""

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
_CLASS_TYPES = {"class_declaration", "struct_declaration", "protocol_declaration", "enum_declaration", "extension_declaration"}
_FN_TYPES = {"function_declaration", "init_declaration", "deinit_declaration"}


@dataclass
class SwiftParser:
    language: str = "swift"
    extensions: tuple[str, ...] = (".swift",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("swift")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="swift", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "import_declaration":
            for g in child.named_children:
                if g.type in ("identifier", "module_name", "path_component"):
                    result.imports.append(ImportEdge(module=node_text(source, g)))
                    break
        elif t in _CLASS_TYPES:
            name = _swift_type_name(child, source)
            emit_class(
                node=child, name=name, module_qname=module_qname,
                parents=parents, sep=".", classes_out=result.classes,
            )
            body = _swift_body(child)
            if body is not None:
                _walk(body, source, module_qname, [*parents, name], result)
        elif t in _FN_TYPES:
            name = _swift_fn_name(child, source, t)
            is_method = bool(parents)
            class_qname = ".".join(p for p in [module_qname, *parents] if p) if parents else None
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=module_qname, parents=parents, sep=".",
                is_method=is_method, is_async=_swift_is_async(child),
                functions_out=result.functions, class_qname=class_qname,
            )
            body = _swift_body(child)
            if body is not None:
                collect_calls(
                    body=body, source=source, caller_qname=fn_qname,
                    call_node_types=_CALL_TYPES, name_extractor=_call_name,
                    calls_out=result.calls,
                )
        else:
            _walk(child, source, module_qname, parents, result)


def _swift_type_name(node, source: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is not None:
        return node_text(source, name)
    for c in node.named_children:
        if c.type in ("type_identifier", "identifier"):
            return node_text(source, c)
    return "?"


def _swift_fn_name(node, source: bytes, ntype: str) -> str:
    if ntype == "init_declaration":
        return "init"
    if ntype == "deinit_declaration":
        return "deinit"
    name = node.child_by_field_name("name")
    if name is not None:
        return node_text(source, name)
    for c in node.named_children:
        if c.type == "simple_identifier":
            return node_text(source, c)
    return "?"


def _swift_body(node):
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for c in node.children:
        if c.type in ("function_body", "code_block", "enum_class_body", "class_body"):
            return c
    return None


def _swift_is_async(node) -> bool:
    return any(c.type == "async" for c in node.children)


def _call_name(n, source: bytes) -> str:
    fn = _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(SwiftParser())

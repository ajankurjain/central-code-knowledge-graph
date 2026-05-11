"""Dart parser via tree-sitter."""

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

_CALL_TYPES = {"call_expression", "method_invocation", "new_expression", "function_expression_invocation"}


@dataclass
class DartParser:
    language: str = "dart"
    extensions: tuple[str, ...] = (".dart",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("dart")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="dart", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t in ("import_or_export", "import_specification", "library_import"):
            for g in child.named_children:
                if g.type in ("string", "uri", "configurable_uri"):
                    result.imports.append(ImportEdge(module=node_text(source, g).strip("\"'")))
                    break
        elif t in ("class_definition", "mixin_declaration", "extension_declaration", "enum_declaration"):
            name = field_text(child, source, "name") or _ident_child(child, source)
            emit_class(
                node=child, name=name, module_qname=module_qname,
                parents=parents, sep=".", classes_out=result.classes,
            )
            body = child.child_by_field_name("body") or _first_body(child)
            if body is not None:
                _walk(body, source, module_qname, [*parents, name], result)
        elif t in ("function_signature", "method_signature", "function_body", "method_declaration", "function_declaration"):
            # Tree-sitter-dart often emits separate signature + body nodes.
            # Treat the *signature* as the function definition site.
            if t in ("function_signature", "method_signature", "function_declaration"):
                name = field_text(child, source, "name") or _ident_child(child, source)
                is_method = bool(parents)
                class_qname = ".".join(p for p in [module_qname, *parents] if p) if parents else None
                fn_qname = emit_function(
                    node=child, source=source, name=name,
                    module_qname=module_qname, parents=parents, sep=".",
                    is_method=is_method, is_async=False,
                    functions_out=result.functions, class_qname=class_qname,
                )
                # Body is usually the next sibling; collect calls if reachable.
                body = _next_body(child)
                if body is not None:
                    collect_calls(
                        body=body, source=source, caller_qname=fn_qname,
                        call_node_types=_CALL_TYPES, name_extractor=_call_name,
                        calls_out=result.calls,
                    )
        else:
            _walk(child, source, module_qname, parents, result)


def _ident_child(node, source: bytes) -> str:
    for c in node.named_children:
        if c.type in ("identifier", "type_identifier"):
            return node_text(source, c)
    return "?"


def _first_body(node):
    for c in node.children:
        if c.type in ("class_body", "block", "function_body"):
            return c
    return None


def _next_body(sig_node):
    parent = sig_node.parent
    if parent is None:
        return None
    seen = False
    for c in parent.children:
        if seen and c.type in ("function_body", "block"):
            return c
        if c == sig_node:
            seen = True
    return None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or n.child_by_field_name("selector") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(DartParser())

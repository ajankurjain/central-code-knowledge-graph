"""Perl parser via tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ckg.parsers._generic import (
    collect_calls,
    emit_function,
    field_text,
    module_qname_from_path,
    trailing_name,
)
from ckg.parsers._ts import get_ts_parser, node_text
from ckg.parsers.base import ImportEdge, ParseResult, register_parser

_CALL_TYPES = {"function_call_expression", "method_call_expression", "call_expression"}


@dataclass
class PerlParser:
    language: str = "perl"
    extensions: tuple[str, ...] = (".pl", ".pm", ".t")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("perl")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="perl", size_bytes=len(source))
        pkg = _package(tree.root_node, source) or module_qname_from_path(path, sep="::")
        _walk(tree.root_node, source, pkg, result)
        return result


def _package(root, source: bytes) -> str:
    for c in root.children:
        if c.type in ("package_statement",):
            for g in c.named_children:
                if g.type in ("package", "identifier"):
                    return node_text(source, g)
    return ""


def _walk(node, source: bytes, pkg: str, result: ParseResult) -> None:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in ("use_statement", "require_statement", "no_statement"):
            for g in n.named_children:
                if g.type in ("package", "identifier", "string"):
                    result.imports.append(ImportEdge(module=node_text(source, g).strip("\"'")))
                    break
        elif n.type in ("subroutine_declaration_statement", "anonymous_subroutine_expression", "method_declaration_statement"):
            name = field_text(n, source, "name") or _ident_child(n, source) or "?"
            fn_qname = emit_function(
                node=n, source=source, name=name,
                module_qname=pkg, parents=[], sep="::",
                is_method=False, is_async=False,
                functions_out=result.functions,
            )
            body = n.child_by_field_name("body")
            if body is not None:
                collect_calls(
                    body=body, source=source, caller_qname=fn_qname,
                    call_node_types=_CALL_TYPES, name_extractor=_call_name,
                    calls_out=result.calls,
                )
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _ident_child(node, source: bytes) -> str:
    for c in node.named_children:
        if c.type in ("bareword", "identifier"):
            return node_text(source, c)
    return ""


def _call_name(n, source: bytes) -> str:
    name = n.child_by_field_name("function") or n.child_by_field_name("name") or _first_named(n)
    return trailing_name(name, source) if name is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(PerlParser())

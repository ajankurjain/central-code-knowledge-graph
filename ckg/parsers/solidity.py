"""Solidity parser via tree-sitter."""

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

_CALL_TYPES = {"call_expression", "member_expression_call", "new_expression"}


@dataclass
class SolidityParser:
    language: str = "solidity"
    extensions: tuple[str, ...] = (".sol",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("solidity")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="solidity", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t in ("import_directive", "import_statement"):
            txt = node_text(source, child)
            # Solidity: import "path"; or import {Foo} from "path";
            # Find the trailing string literal.
            for g in child.named_children:
                if g.type in ("string", "string_literal"):
                    result.imports.append(ImportEdge(
                        module=node_text(source, g).strip("\"'"),
                        is_relative=("./" in txt) or ("../" in txt),
                    ))
                    break
        elif t in ("contract_declaration", "interface_declaration", "library_declaration"):
            name = field_text(child, source, "name") or "?"
            emit_class(
                node=child, name=name, module_qname=module_qname,
                parents=parents, sep=".", classes_out=result.classes,
            )
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, parents + [name], result)
        elif t in ("function_definition", "modifier_definition", "constructor_definition", "fallback_receive_definition", "receive_definition"):
            name = field_text(child, source, "name") or {"constructor_definition": "constructor", "receive_definition": "receive", "fallback_receive_definition": "fallback"}.get(t, "?")
            is_method = bool(parents)
            class_qname = ".".join(p for p in [module_qname, *parents] if p) if parents else None
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=module_qname, parents=parents, sep=".",
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
            _walk(child, source, module_qname, parents, result)


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or n.child_by_field_name("name") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


register_parser(SolidityParser())

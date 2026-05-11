"""Julia parser via tree-sitter."""

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

_CALL_TYPES = {"call_expression", "function_call"}


@dataclass
class JuliaParser:
    language: str = "julia"
    extensions: tuple[str, ...] = (".jl",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("julia")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="julia", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t in ("using_statement", "import_statement"):
            for g in child.named_children:
                if g.type in ("identifier", "scoped_identifier", "module_name", "import_path"):
                    result.imports.append(ImportEdge(module=node_text(source, g)))
        elif t in ("module_definition", "baremodule_definition"):
            name = field_text(child, source, "name") or "?"
            body = child.child_by_field_name("body") or child
            _walk(body, source, f"{module_qname}.{name}" if module_qname else name, parents, result)
        elif t in ("struct_definition", "abstract_definition", "primitive_definition", "type_definition"):
            name = field_text(child, source, "name") or "?"
            emit_class(
                node=child, name=name, module_qname=module_qname,
                parents=parents, sep=".", classes_out=result.classes,
            )
        elif t in ("function_definition", "short_function_definition", "macro_definition", "assignment_expression"):
            if t == "assignment_expression":
                # f(x) = ... shorthand — skip if RHS isn't function-like
                rhs = child.child_by_field_name("value") or _last_named(child)
                if rhs is None or rhs.type not in ("call_expression", "function_call"):
                    continue
                lhs = child.child_by_field_name("lhs") or _first_named(child)
                if lhs is None or lhs.type not in ("call_expression", "function_call"):
                    continue
                name_node = lhs.child_by_field_name("function") or _first_named(lhs)
                name = node_text(source, name_node) if name_node is not None else "?"
            else:
                name_node = child.child_by_field_name("name") or _signature_name(child, source)
                name = node_text(source, name_node) if name_node is not None else "?"
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=module_qname, parents=parents, sep=".",
                is_method=False, is_async=False,
                functions_out=result.functions,
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


def _signature_name(n, source: bytes):
    sig = n.child_by_field_name("signature") or _first_named(n)
    if sig is None:
        return None
    name = sig.child_by_field_name("function") or _first_named(sig)
    return name


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


def _last_named(n):
    return n.named_children[-1] if n.named_child_count > 0 else None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


register_parser(JuliaParser())

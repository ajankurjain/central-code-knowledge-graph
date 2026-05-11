"""C# parser via tree-sitter."""

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

_CALL_TYPES = {"invocation_expression", "object_creation_expression"}


@dataclass
class CSharpParser:
    language: str = "csharp"
    extensions: tuple[str, ...] = (".cs",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("csharp")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="csharp", size_bytes=len(source))
        ns = _file_namespace(tree.root_node, source) or module_qname_from_path(path)
        _walk(tree.root_node, source, ns, parents=[], result=result)
        return result


def _file_namespace(root, source: bytes) -> str:
    for c in root.children:
        if c.type in ("namespace_declaration", "file_scoped_namespace_declaration"):
            name = c.child_by_field_name("name")
            if name is not None:
                return node_text(source, name)
    return ""


def _walk(node, source: bytes, ns: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "using_directive":
            mod = _using_target(child, source)
            if mod:
                result.imports.append(ImportEdge(module=mod))
        elif t in ("namespace_declaration", "file_scoped_namespace_declaration"):
            sub = child.child_by_field_name("name")
            sub_ns = node_text(source, sub) if sub is not None else ""
            body = child.child_by_field_name("body")
            target_ns = f"{ns}.{sub_ns}" if ns and sub_ns else sub_ns or ns
            if body is not None:
                _walk(body, source, target_ns, parents, result)
        elif t in ("class_declaration", "interface_declaration", "struct_declaration", "record_declaration", "enum_declaration"):
            name = field_text(child, source, "name") or "?"
            class_qname = emit_class(
                node=child, name=name, module_qname=ns, parents=parents,
                sep=".", classes_out=result.classes,
            )
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, ns, [*parents, name], result)
            # We already wrote the class node; suppress fallthrough.
            continue
        elif t in ("method_declaration", "constructor_declaration", "destructor_declaration", "operator_declaration", "local_function_statement"):
            name = field_text(child, source, "name") or "?"
            is_method = bool(parents)
            class_qname = ".".join(p for p in [ns, *parents] if p) if parents else None
            fn_qname = emit_function(
                node=child, source=source, name=name,
                module_qname=ns, parents=parents, sep=".",
                is_method=is_method, is_async=_is_async(child),
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


def _is_async(node) -> bool:
    for c in node.children:
        if c.type == "modifier" and any(g.type == "async" for g in c.children):
            return True
        if c.type == "async":
            return True
    return False


def _using_target(node, source: bytes) -> str:
    for c in node.named_children:
        if c.type in ("qualified_name", "identifier"):
            return node_text(source, c)
    return ""


def _call_name(n, source: bytes) -> str:
    if n.type == "invocation_expression":
        fn = n.child_by_field_name("function")
        return trailing_name(fn, source) if fn is not None else ""
    if n.type == "object_creation_expression":
        ty = n.child_by_field_name("type")
        return trailing_name(ty, source) if ty is not None else ""
    return ""


register_parser(CSharpParser())

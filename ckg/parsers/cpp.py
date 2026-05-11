"""C++ parser via tree-sitter.

Supports classes (including nested), namespaces, member functions, function
templates, `using` declarations / namespaces, and includes.
"""

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
class CppParser:
    language: str = "cpp"
    extensions: tuple[str, ...] = (".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("cpp")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="cpp", size_bytes=len(source))
        module_qname = _module_qname(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _module_qname(path: Path) -> str:
    return "::".join(path.with_suffix("").parts)


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t == "preproc_include":
            inc = child.child_by_field_name("path")
            if inc is not None:
                mod = node_text(source, inc).strip("\"<>")
                result.imports.append(ImportEdge(
                    module=mod,
                    is_relative=node_text(source, inc).startswith("\""),
                ))
        elif t == "using_declaration":
            # `using std::vector;` — treat the trailing scoped_identifier as an import.
            for c in child.named_children:
                if c.type in ("scoped_identifier", "identifier"):
                    result.imports.append(ImportEdge(module=node_text(source, c)))
        elif t == "namespace_definition":
            name_node = child.child_by_field_name("name")
            ns = node_text(source, name_node) if name_node is not None else ""
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, parents + ([ns] if ns else []), result)
        elif t in ("class_specifier", "struct_specifier", "union_specifier"):
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "?"
            qname_parts = [module_qname, *parents, name]
            qname = "::".join(p for p in qname_parts if p)
            result.classes.append(ClassNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
            ))
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, [*parents, name], result)
        elif t == "function_definition":
            _emit_function(child, source, module_qname, parents, result)
        elif t == "template_declaration":
            # Descend; the template wraps a function_definition or class_specifier
            _walk(child, source, module_qname, parents, result)
        elif t == "linkage_specification":
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, parents, result)
        else:
            _walk(child, source, module_qname, parents, result)


def _emit_function(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    declarator = node.child_by_field_name("declarator")
    name, scope_qual = _function_name_and_scope(declarator, source) if declarator is not None else ("?", "")
    is_method = bool(parents) or bool(scope_qual)
    class_qname = None
    if scope_qual:
        # e.g. `Foo::Bar::method` — class_qname is the prefix
        class_qname = "::".join(p for p in [module_qname, scope_qual] if p)
        qname = f"{class_qname}::{name}"
    elif parents:
        class_qname = "::".join(p for p in [module_qname, *parents] if p)
        qname = f"{class_qname}::{name}"
    else:
        qname = "::".join(p for p in [module_qname, name] if p)
    body_text = node_text(source, node)
    fn = FunctionNode(
        name=name, qualified_name=qname,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        is_method=is_method,
        is_async=False,
        body=body_text,
        body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
        class_qname=class_qname,
    )
    result.functions.append(fn)
    body = node.child_by_field_name("body")
    if body is not None:
        _collect_calls(body, source, fn.qualified_name, result)


def _function_name_and_scope(declarator, source: bytes) -> tuple[str, str]:
    """Return (name, scope_qualifier).  scope_qualifier is non-empty when the
    function is defined out-of-line, e.g. `void Foo::Bar::method()`."""
    n = declarator
    while n is not None:
        if n.type == "identifier":
            return node_text(source, n), ""
        if n.type == "qualified_identifier":
            # scope::name (possibly nested scope::scope::name)
            scope = n.child_by_field_name("scope")
            name = n.child_by_field_name("name")
            if name is not None:
                name_text = node_text(source, name)
                scope_text = node_text(source, scope) if scope is not None else ""
                # name may itself be qualified_identifier (e.g. operator+)
                if name.type == "qualified_identifier":
                    inner, deeper = _function_name_and_scope(name, source)
                    full_scope = "::".join(p for p in [scope_text, deeper] if p)
                    return inner, full_scope
                return name_text, scope_text
            return "", ""
        if n.type == "function_declarator":
            n = n.child_by_field_name("declarator")
            continue
        if n.type in ("pointer_declarator", "reference_declarator"):
            n = n.child_by_field_name("declarator")
            continue
        if n.type == "parenthesized_declarator" and n.named_child_count > 0:
            n = n.named_children[0]
            continue
        return "", ""
    return "", ""


def _collect_calls(body, source: bytes, caller_qname: str, result: ParseResult) -> None:
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            fn_node = n.child_by_field_name("function")
            if fn_node is not None:
                callee = _call_target(fn_node, source)
                if callee:
                    result.calls.append(CallEdge(
                        caller_qname=caller_qname,
                        callee_name=callee,
                        line=n.start_point[0] + 1,
                    ))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _call_target(fn_node, source: bytes) -> str:
    if fn_node.type == "identifier":
        return node_text(source, fn_node)
    if fn_node.type == "field_expression":
        field = fn_node.child_by_field_name("field")
        return node_text(source, field) if field is not None else ""
    if fn_node.type == "qualified_identifier":
        name = fn_node.child_by_field_name("name")
        return node_text(source, name) if name is not None else ""
    if fn_node.type == "parenthesized_expression" and fn_node.named_child_count > 0:
        return _call_target(fn_node.named_children[0], source)
    return ""


register_parser(CppParser())

"""JavaScript / TypeScript parser (one parser for both — same grammar family)."""

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

_TS_EXT = {".ts", ".tsx", ".mts", ".cts"}
_JS_EXT = {".js", ".jsx", ".mjs", ".cjs"}


@dataclass
class JsTsParser:
    language: str = "javascript"
    # We register one parser for the union of extensions; ParseResult.language
    # is set per-file based on suffix.
    extensions: tuple[str, ...] = tuple(_JS_EXT | _TS_EXT)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        suf = path.suffix.lower()
        if suf in _TS_EXT:
            lang = "tsx" if suf == ".tsx" else "typescript"
            display_lang = "typescript"
        else:
            lang = "javascript"
            display_lang = "javascript"
        try:
            parser = get_ts_parser(lang)
        except Exception:
            parser = get_ts_parser("javascript")
            display_lang = "javascript"

        tree = parser.parse(source)
        root = tree.root_node
        result = ParseResult(path=str(path), language=display_lang, size_bytes=len(source))

        module_qname = _module_qname(path)
        _walk(root, source, module_qname, parents=[], result=result)
        return result


def _module_qname(path: Path) -> str:
    return ".".join(path.with_suffix("").parts)


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t in ("import_statement",):
            mod = _import_source(child, source)
            if mod:
                result.imports.append(ImportEdge(module=mod))
        elif t == "class_declaration":
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "?"
            qname = ".".join([module_qname, *parents, name])
            result.classes.append(ClassNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
            ))
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, [*parents, name], result)
        elif t in ("function_declaration", "method_definition", "arrow_function", "function_expression"):
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "<anon>"
            qname = ".".join([module_qname, *parents, name])
            body_text = node_text(source, child)
            is_method = t == "method_definition"
            fn = FunctionNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                is_method=is_method,
                is_async=_is_async(child, source),
                body=body_text,
                body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
                class_qname=".".join([module_qname, *parents]) if is_method else None,
            )
            result.functions.append(fn)
            body = child.child_by_field_name("body")
            if body is not None:
                _collect_calls(body, source, fn.qualified_name, result)
        else:
            _walk(child, source, module_qname, parents, result)


def _is_async(node, source: bytes) -> bool:
    return any(c.type == "async" for c in node.children)


def _import_source(node, source: bytes) -> str:
    for c in node.children:
        if c.type == "string":
            return node_text(source, c).strip("'\"`")
    return ""


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
    if fn_node.type == "member_expression":
        prop = fn_node.child_by_field_name("property")
        return node_text(source, prop) if prop is not None else ""
    return ""


register_parser(JsTsParser())

"""Lua parser via tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ckg.parsers._generic import (
    collect_calls,
    emit_function,
    module_qname_from_path,
    trailing_name,
)
from ckg.parsers._ts import get_ts_parser, node_text
from ckg.parsers.base import ImportEdge, ParseResult, register_parser

_CALL_TYPES = {"function_call", "function_call_expression"}

# Modern tree-sitter-lua emits `function_declaration`, `local_function`, and
# `function_definition` (anonymous). Older grammars used the `*_statement`
# suffix. Cover both so the parser works across versions.
_FN_DECL_TYPES = {
    "function_declaration",
    "function_declaration_statement",
    "function_definition_statement",
    "local_function",
    "local_function_declaration_statement",
    "local_function_definition_statement",
}


@dataclass
class LuaParser:
    language: str = "lua"
    extensions: tuple[str, ...] = (".lua",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("lua")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="lua", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, result)
        return result


def _walk(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in _FN_DECL_TYPES:
            name = _ident_child(n, source)
            fn_qname = emit_function(
                node=n, source=source, name=name or "?",
                module_qname=module_qname, parents=[], sep=".",
                is_method=False, is_async=False,
                functions_out=result.functions,
            )
            body = n.child_by_field_name("body") or _first_block(n)
            if body is not None:
                collect_calls(
                    body=body, source=source, caller_qname=fn_qname,
                    call_node_types=_CALL_TYPES, name_extractor=_call_name,
                    calls_out=result.calls,
                )
        elif n.type == "function_call":
            # require("foo") at top-level → import
            fn = n.child_by_field_name("function") or _first_named(n)
            if fn is not None and fn.type == "identifier" and node_text(source, fn) == "require":
                args = n.child_by_field_name("arguments") or _last_named(n)
                if args is not None:
                    for g in args.named_children:
                        if g.type in ("string", "string_content"):
                            result.imports.append(ImportEdge(module=node_text(source, g).strip("\"'[]")))
                            break
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _ident_child(node, source: bytes) -> str:
    # The function name lives in different places depending on grammar version:
    #   modern: `name` field → identifier / dot_index_expression
    #   older:  first named_child of certain types
    name = node.child_by_field_name("name")
    if name is not None:
        return node_text(source, name)
    for c in node.named_children:
        if c.type in (
            "identifier",
            "function_name",
            "method_index_expression",
            "dot_index_expression",
        ):
            return node_text(source, c)
    return ""


def _first_block(node):
    for c in node.children:
        if c.type in ("block",):
            return c
    return None


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


def _last_named(n):
    return n.named_children[-1] if n.named_child_count > 0 else None


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("function") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


register_parser(LuaParser())

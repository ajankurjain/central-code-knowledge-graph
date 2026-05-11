"""PowerShell parser via tree-sitter."""

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

_CALL_TYPES = {"command", "command_expression"}


@dataclass
class PowerShellParser:
    language: str = "powershell"
    extensions: tuple[str, ...] = (".ps1", ".psm1", ".psd1")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("powershell")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="powershell", size_bytes=len(source))
        module_qname = module_qname_from_path(path)
        _walk(tree.root_node, source, module_qname, result)
        return result


def _walk(node, source: bytes, module_qname: str, result: ParseResult) -> None:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in ("function_statement", "function_definition"):
            name_node = n.child_by_field_name("name") or _first_named(n)
            name = node_text(source, name_node) if name_node is not None else "?"
            fn_qname = emit_function(
                node=n, source=source, name=name,
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
        elif n.type in ("command",):
            # Import-Module / Using module / using namespace at script root
            name = _command_name(n, source)
            if name in ("Import-Module", "import-module", "Using", "using"):
                for arg in n.named_children:
                    if arg.type in ("string", "expandable_string", "verbatim_string", "argument_expression"):
                        result.imports.append(ImportEdge(module=node_text(source, arg).strip("\"'")))
                        break
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _first_named(n):
    return n.named_children[0] if n.named_child_count > 0 else None


def _first_block(n):
    for c in n.children:
        if c.type in ("script_block", "statement_block", "block"):
            return c
    return None


def _command_name(n, source: bytes) -> str:
    name = n.child_by_field_name("name") or _first_named(n)
    return node_text(source, name) if name is not None else ""


def _call_name(n, source: bytes) -> str:
    fn = n.child_by_field_name("name") or _first_named(n)
    return trailing_name(fn, source) if fn is not None else ""


register_parser(PowerShellParser())

"""Ruby parser via tree-sitter."""

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
class RubyParser:
    language: str = "ruby"
    extensions: tuple[str, ...] = (".rb",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("ruby")
        tree = parser.parse(source)
        result = ParseResult(path=str(path), language="ruby", size_bytes=len(source))
        module_qname = _module_qname(path)
        _walk(tree.root_node, source, module_qname, parents=[], result=result)
        return result


def _module_qname(path: Path) -> str:
    return "::".join(path.with_suffix("").parts)


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    for child in node.children:
        t = child.type
        if t in ("class", "module"):
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "?"
            qname = "::".join([module_qname, *parents, name])
            result.classes.append(ClassNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
            ))
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, [*parents, name], result)
        elif t in ("method", "singleton_method"):
            name_node = child.child_by_field_name("name")
            name = node_text(source, name_node) if name_node is not None else "?"
            qname = "::".join([module_qname, *parents, name])
            body_text = node_text(source, child)
            is_method = bool(parents)
            fn = FunctionNode(
                name=name, qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                is_method=is_method,
                is_async=False,
                body=body_text,
                body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
                class_qname="::".join([module_qname, *parents]) if is_method else None,
            )
            result.functions.append(fn)
            body = child.child_by_field_name("body")
            if body is not None:
                _collect_calls(body, source, fn.qualified_name, result)
        elif t == "call":
            # Top-level requires: `require "foo"` is parsed as a call
            method_node = child.child_by_field_name("method")
            if method_node is not None and node_text(source, method_node) in ("require", "require_relative", "load", "autoload"):
                args = child.child_by_field_name("arguments")
                if args is not None:
                    for arg in args.named_children:
                        if arg.type == "string":
                            mod = node_text(source, arg).strip("\"' ")
                            result.imports.append(ImportEdge(
                                module=mod,
                                is_relative=node_text(source, method_node) == "require_relative",
                            ))
            _walk(child, source, module_qname, parents, result)
        else:
            _walk(child, source, module_qname, parents, result)


def _collect_calls(body, source: bytes, caller_qname: str, result: ParseResult) -> None:
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "call":
            method_node = n.child_by_field_name("method")
            if method_node is not None:
                callee = node_text(source, method_node)
                # skip the require/load family we treat as imports above
                if callee not in ("require", "require_relative", "load", "autoload"):
                    result.calls.append(CallEdge(
                        caller_qname=caller_qname,
                        callee_name=callee,
                        line=n.start_point[0] + 1,
                    ))
        elif n.type == "identifier":
            # bare-name calls like `foo` (no receiver, no parens) are identifiers in ruby
            # We deliberately don't emit them as calls — too noisy.
            pass
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


register_parser(RubyParser())

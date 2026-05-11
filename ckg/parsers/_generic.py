"""Shared helpers for the language-specific parsers.

Each parser still owns its own walk loop (because node-type names + field
conventions vary), but the *emit* helpers and call-collection routines
look the same across languages, so we centralize them here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from ckg.parsers._ts import node_text
from ckg.parsers.base import CallEdge, ClassNode, FunctionNode


def sha_of(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def field_text(node, source: bytes, field: str) -> str:
    """Read `node.child_by_field_name(field)` as text; empty string if missing."""
    if node is None:
        return ""
    sub = node.child_by_field_name(field)
    return node_text(source, sub) if sub is not None else ""


def first_child_of_type(node, types: Iterable[str]):
    types = set(types)
    for c in node.children:
        if c.type in types:
            return c
    return None


def first_named_of_type(node, types: Iterable[str]):
    types = set(types)
    for c in node.named_children:
        if c.type in types:
            return c
    return None


def module_qname_from_path(path: Path, sep: str = ".") -> str:
    parts = list(path.with_suffix("").parts)
    return sep.join(p for p in parts if p and p not in (".", "/"))


def emit_class(
    *,
    node,
    name: str,
    module_qname: str,
    parents: list[str],
    sep: str,
    classes_out: list[ClassNode],
    doc: str = "",
) -> str:
    """Append a ClassNode and return its qualified name."""
    parts = [p for p in [module_qname, *parents, name] if p]
    qname = sep.join(parts)
    classes_out.append(ClassNode(
        name=name or "?",
        qualified_name=qname or "?",
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        doc=doc,
    ))
    return qname


def emit_function(
    *,
    node,
    source: bytes,
    name: str,
    module_qname: str,
    parents: list[str],
    sep: str,
    is_method: bool,
    is_async: bool,
    functions_out: list[FunctionNode],
    doc: str = "",
    class_qname: str | None = None,
) -> str:
    body_text = node_text(source, node)
    parts = [p for p in [module_qname, *parents, name] if p]
    qname = sep.join(parts) or name or "?"
    functions_out.append(FunctionNode(
        name=name or "?",
        qualified_name=qname,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        is_method=is_method,
        is_async=is_async,
        body=body_text,
        body_sha=sha_of(body_text),
        doc=doc,
        class_qname=class_qname,
    ))
    return qname


def collect_calls(
    *,
    body,
    source: bytes,
    caller_qname: str,
    call_node_types: set[str],
    name_extractor,
    calls_out: list[CallEdge],
) -> None:
    """Iterative DFS through `body` collecting CallEdge for every node whose
    type is in `call_node_types`. `name_extractor(node, source)` returns the
    callee's short name (or empty to skip)."""
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type in call_node_types:
            name = name_extractor(n, source)
            if name:
                calls_out.append(CallEdge(
                    caller_qname=caller_qname,
                    callee_name=name,
                    line=n.start_point[0] + 1,
                    character=n.start_point[1],
                ))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def trailing_name(node, source: bytes) -> str:
    """For chained / qualified call targets (`a.b.c(…)`), return the trailing
    short name. Tries the `attribute`, `property`, `field`, `name`, `member`
    fields; falls back to the last identifier child."""
    if node is None:
        return ""
    if node.type == "identifier":
        return node_text(source, node)
    for field in ("attribute", "property", "field", "name", "member"):
        sub = node.child_by_field_name(field)
        if sub is not None:
            return node_text(source, sub)
    # Walk to the trailing identifier child
    last = None
    for c in node.named_children:
        if c.type in ("identifier", "field_identifier"):
            last = c
    return node_text(source, last) if last is not None else ""

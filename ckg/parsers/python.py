"""Python parser via tree-sitter."""

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
class PythonParser:
    language: str = "python"
    extensions: tuple[str, ...] = (".py", ".pyi")

    def parse(self, path: Path, source: bytes) -> ParseResult:
        parser = get_ts_parser("python")
        tree = parser.parse(source)
        root = tree.root_node

        result = ParseResult(
            path=str(path),
            language="python",
            size_bytes=len(source),
        )

        module_qname = _module_qname(path)
        _walk(root, source, module_qname, parents=[], result=result)
        return result


def _module_qname(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    # Strip leading "/" or volume prefixes; the worker passes a repo-relative path
    return ".".join(p for p in parts if p and p not in (".", "/"))


def _walk(node, source: bytes, module_qname: str, parents: list[str], result: ParseResult) -> None:
    """Recursive structural walk (one level of class nesting is the common case)."""
    for child in node.children:
        if child.type == "import_statement" or child.type == "import_from_statement":
            for imp in _imports(child, source):
                result.imports.append(imp)
        elif child.type == "class_definition":
            cname = _ident(child.child_by_field_name("name"), source)
            qname = ".".join([module_qname, *parents, cname]) if cname else module_qname
            result.classes.append(ClassNode(
                name=cname or "?",
                qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                doc=_docstring(child, source),
            ))
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, source, module_qname, [*parents, cname or "?"], result)
        elif child.type in ("function_definition", "async_function_definition"):
            fname = _ident(child.child_by_field_name("name"), source)
            qname = ".".join([module_qname, *parents, fname]) if fname else module_qname
            is_method = bool(parents)
            body_text = node_text(source, child)
            fn = FunctionNode(
                name=fname or "?",
                qualified_name=qname,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                is_method=is_method,
                is_async=(child.type == "async_function_definition"),
                doc=_docstring(child, source),
                body=body_text,
                body_sha=hashlib.sha1(body_text.encode("utf-8", "replace")).hexdigest(),
                class_qname=".".join([module_qname, *parents]) if is_method else None,
            )
            result.functions.append(fn)
            # Walk function body for call edges
            body = child.child_by_field_name("body")
            if body is not None:
                _collect_calls(body, source, fn.qualified_name, result)
        else:
            _walk(child, source, module_qname, parents, result)


def _ident(node, source: bytes) -> str:
    if node is None:
        return ""
    return node_text(source, node)


def _docstring(def_node, source: bytes) -> str:
    body = def_node.child_by_field_name("body")
    if body is None or body.child_count == 0:
        return ""
    first = body.children[0]
    if first.type == "expression_statement" and first.child_count > 0:
        expr = first.children[0]
        if expr.type == "string":
            return node_text(source, expr).strip("\"' \n")
    return ""


def _imports(node, source: bytes) -> list[ImportEdge]:
    out: list[ImportEdge] = []
    txt = node_text(source, node)
    if node.type == "import_statement":
        for n in node.named_children:
            if n.type == "dotted_name":
                out.append(ImportEdge(module=node_text(source, n)))
            elif n.type == "aliased_import":
                name = n.child_by_field_name("name")
                alias = n.child_by_field_name("alias")
                if name is not None:
                    out.append(ImportEdge(
                        module=node_text(source, name),
                        alias=node_text(source, alias) if alias is not None else None,
                    ))
    elif node.type == "import_from_statement":
        module_node = node.child_by_field_name("module_name")
        if module_node is None:
            return out
        mod = node_text(source, module_node)
        is_rel = txt.lstrip().startswith("from .")
        # `from x import a, b as c` — record each
        for n in node.named_children:
            if n is module_node:
                continue
            if n.type == "dotted_name":
                out.append(ImportEdge(module=f"{mod}.{node_text(source, n)}", is_relative=is_rel))
            elif n.type == "aliased_import":
                name = n.child_by_field_name("name")
                alias = n.child_by_field_name("alias")
                if name is not None:
                    out.append(ImportEdge(
                        module=f"{mod}.{node_text(source, name)}",
                        alias=node_text(source, alias) if alias is not None else None,
                        is_relative=is_rel,
                    ))
    return out


def _collect_calls(body, source: bytes, caller_qname: str, result: ParseResult) -> None:
    """Find `name(...)` and `obj.name(...)` call sites inside a function body."""
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "call":
            fn_node = n.child_by_field_name("function")
            if fn_node is not None:
                callee = _call_target(fn_node, source)
                if callee:
                    result.calls.append(CallEdge(
                        caller_qname=caller_qname,
                        callee_name=callee,
                        line=fn_node.start_point[0] + 1,
                        character=fn_node.start_point[1],
                    ))
        for i in range(n.child_count - 1, -1, -1):
            stack.append(n.children[i])


def _call_target(fn_node, source: bytes) -> str:
    if fn_node.type == "identifier":
        return node_text(source, fn_node)
    if fn_node.type == "attribute":
        attr = fn_node.child_by_field_name("attribute")
        return node_text(source, attr) if attr is not None else ""
    return ""


register_parser(PythonParser())

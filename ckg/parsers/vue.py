"""Vue single-file-component parser.

Vue SFCs are a `<template>...</template> <script[ setup][ lang=ts]>...</script>
<style>...</style>` document. The structural symbols live in the `<script>`
block; the template is HTML and the style is CSS. We extract the script
block (preserving its line offset) and delegate to the JS/TS parser, then
adjust the reported line numbers so they index into the original `.vue` file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ckg.parsers.base import (
    CallEdge,
    ClassNode,
    FunctionNode,
    ImportEdge,
    ParseResult,
    register_parser,
)
from ckg.parsers.javascript import JsTsParser

# Closing tag accepts any junk between `script` and `>` (e.g. `</script bar>`,
# `</script\n>`, `</script >`). The HTML5 parser tolerates that, so the regex
# must too — otherwise an unusual-but-valid SFC would leave a `<script>` block
# unclosed and we'd silently drop the content (flagged by CodeQL py/bad-tag-filter).
_SCRIPT_BLOCK = re.compile(
    rb"<script\b([^>]*)>(.*?)</script[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_LANG_ATTR = re.compile(rb'lang\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


@dataclass
class VueParser:
    language: str = "vue"
    extensions: tuple[str, ...] = (".vue",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        result = ParseResult(path=str(path), language="vue", size_bytes=len(source))
        for match in _SCRIPT_BLOCK.finditer(source):
            attrs, script_body = match.group(1), match.group(2)
            line_offset = source.count(b"\n", 0, match.start(2))
            inner_path = _virtual_inner_path(path, attrs)
            inner = JsTsParser().parse(inner_path, script_body)
            _merge(result, inner, line_offset)
        return result


def _virtual_inner_path(path: Path, attrs: bytes) -> Path:
    """Pick `.ts` vs `.js` so the JS/TS parser picks the right grammar."""
    m = _LANG_ATTR.search(attrs)
    lang = (m.group(1).decode("ascii", "ignore").lower() if m else "") or "js"
    suffix = {"ts": ".ts", "typescript": ".ts", "tsx": ".tsx", "jsx": ".jsx"}.get(lang, ".js")
    return path.with_suffix(suffix)


def _merge(outer: ParseResult, inner: ParseResult, line_offset: int) -> None:
    for c in inner.classes:
        outer.classes.append(ClassNode(
            name=c.name, qualified_name=c.qualified_name,
            start_line=c.start_line + line_offset,
            end_line=c.end_line + line_offset,
            doc=c.doc,
        ))
    for fn in inner.functions:
        outer.functions.append(FunctionNode(
            name=fn.name, qualified_name=fn.qualified_name,
            start_line=fn.start_line + line_offset,
            end_line=fn.end_line + line_offset,
            is_method=fn.is_method, is_async=fn.is_async,
            doc=fn.doc, body=fn.body, body_sha=fn.body_sha,
            class_qname=fn.class_qname,
        ))
    for imp in inner.imports:
        outer.imports.append(ImportEdge(
            module=imp.module, alias=imp.alias, is_relative=imp.is_relative,
        ))
    for call in inner.calls:
        outer.calls.append(CallEdge(
            caller_qname=call.caller_qname, callee_name=call.callee_name,
            line=call.line + line_offset, character=call.character,
        ))


register_parser(VueParser())

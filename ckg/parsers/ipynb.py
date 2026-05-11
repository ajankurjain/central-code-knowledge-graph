"""Jupyter / Databricks notebook (.ipynb) parser.

Notebooks are JSON. We extract `cell_type == "code"` cells, concatenate them
(preserving cell boundaries as blank lines), look up the kernel language
from `metadata.kernelspec.language` (default: python), and delegate to the
matching registered parser. Cell lines map 1:1 to the synthetic source —
that's correct for Jupyter's "Open by line" workflows; the synthetic file
shows the original cell layout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ckg.parsers.base import ParseResult, get_parser, register_parser

# Map common kernelspec.language → our registered parser language.
_KERNEL_LANG_MAP = {
    "python": "python",
    "ir": "r",
    "r": "r",
    "julia": "julia",
    "scala": "scala",
    "javascript": "javascript",
    "typescript": "javascript",  # share the parser
    "ruby": "ruby",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "c#": "csharp",
    "csharp": "csharp",
    "powershell": "powershell",
    "bash": None,
    "shell": None,
    "sh": None,
}

_FILE_EXT_FOR_LANG = {
    "python": ".py", "r": ".R", "julia": ".jl", "scala": ".scala",
    "javascript": ".js", "ruby": ".rb", "go": ".go", "rust": ".rs",
    "java": ".java", "csharp": ".cs", "powershell": ".ps1",
}


@dataclass
class JupyterParser:
    language: str = "ipynb"
    extensions: tuple[str, ...] = (".ipynb",)

    def parse(self, path: Path, source: bytes) -> ParseResult:
        result = ParseResult(path=str(path), language="ipynb", size_bytes=len(source))
        try:
            doc = json.loads(source.decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError:
            return result

        kernel_lang = _kernel_language(doc)
        target_lang = _KERNEL_LANG_MAP.get(kernel_lang)
        if target_lang is None:
            return result
        parser = get_parser(target_lang)
        if parser is None:
            return result

        synthetic = _concat_code_cells(doc)
        if not synthetic:
            return result

        inner_path = path.with_suffix(_FILE_EXT_FOR_LANG.get(target_lang, ".txt"))
        inner = parser.parse(inner_path, synthetic.encode("utf-8"))

        # Inner ParseResult already has correct line numbers relative to the
        # synthetic source; we just copy them through and overwrite `language`
        # so the graph still labels this as a notebook.
        result.classes.extend(inner.classes)
        result.functions.extend(inner.functions)
        result.imports.extend(inner.imports)
        result.calls.extend(inner.calls)
        result.language = f"ipynb/{target_lang}"
        return result


def _kernel_language(doc: dict) -> str:
    meta = doc.get("metadata", {}) or {}
    kspec = meta.get("kernelspec", {}) or {}
    lang_info = meta.get("language_info", {}) or {}
    raw = (kspec.get("language") or lang_info.get("name") or "python")
    return str(raw).lower().strip()


def _concat_code_cells(doc: dict) -> str:
    """Return a single string of all code cells, separated by blank lines so
    line numbers line up reasonably."""
    out: list[str] = []
    for cell in doc.get("cells", []) or []:
        if cell.get("cell_type") != "code":
            # Preserve line count of non-code cells by emitting a blank block
            # of the same height — keeps line numbers honest.
            src = cell.get("source") or []
            out.append(_count_lines_blank(src))
            continue
        src = cell.get("source") or []
        if isinstance(src, list):
            out.append("".join(src))
        elif isinstance(src, str):
            out.append(src)
        # Cell separator: a blank line so consecutive cells don't merge tokens.
        if not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append("\n")
    return "".join(out)


def _count_lines_blank(src) -> str:
    """For a non-code cell, emit an equal number of newlines so subsequent
    code-cell line numbers line up with the .ipynb's visible layout."""
    if isinstance(src, list):
        n = sum(s.count("\n") for s in src) + (1 if src else 0)
    elif isinstance(src, str):
        n = src.count("\n") + 1
    else:
        n = 1
    return "\n" * n


register_parser(JupyterParser())

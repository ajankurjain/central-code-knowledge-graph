"""End-to-end test of the Python tree-sitter parser.

We don't touch Neo4j here — we just assert the parser builds the right
ParseResult shape from a sample source file.
"""

from pathlib import Path

import pytest

try:
    from tree_sitter_language_pack import get_language  # noqa: F401

    HAS_TS = True
except ImportError:  # pragma: no cover
    HAS_TS = False

from ckg.parsers import get_parser


SAMPLE = b'''
"""module docstring"""
import os
from pathlib import Path as P

class Greeter:
    """says hi"""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return _format(self.name)

def _format(name: str) -> str:
    return f"hello, {name}"

async def main() -> None:
    g = Greeter("world")
    print(g.greet())
'''


@pytest.mark.skipif(not HAS_TS, reason="tree-sitter-language-pack not installed")
def test_python_parser_extracts_basic_shape():
    parser = get_parser("python")
    assert parser is not None
    result = parser.parse(Path("sample.py"), SAMPLE)

    fn_names = {fn.name for fn in result.functions}
    assert {"__init__", "greet", "_format", "main"}.issubset(fn_names)

    cls_names = {c.name for c in result.classes}
    assert "Greeter" in cls_names

    # main is async
    main_fn = next(fn for fn in result.functions if fn.name == "main")
    assert main_fn.is_async is True

    # greet calls _format
    callees = {c.callee_name for c in result.calls if c.caller_qname.endswith("greet")}
    assert "_format" in callees

    # imports captured
    modules = {imp.module for imp in result.imports}
    assert "os" in modules
    assert any("pathlib" in m for m in modules)

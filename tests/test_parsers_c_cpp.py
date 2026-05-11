"""Sanity tests for the C and C++ parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from tree_sitter_language_pack import get_language  # noqa: F401

    HAS_TS = True
except ImportError:  # pragma: no cover
    HAS_TS = False

from ckg.parsers import get_parser

pytestmark = pytest.mark.skipif(not HAS_TS, reason="tree-sitter-language-pack not installed")


def _names(parsed) -> set[str]:
    return {fn.name for fn in parsed.functions}


def test_c_parser():
    src = b'''
#include <stdio.h>
#include "helper.h"

struct Greeter { const char *name; };

static const char *format_name(const char *n) { return n; }

int greet(struct Greeter *g) {
    return printf("hello, %s\\n", format_name(g->name));
}
'''
    parser = get_parser("c")
    assert parser is not None
    parsed = parser.parse(Path("greeter.c"), src)
    assert parsed.language == "c"
    assert {"format_name", "greet"}.issubset(_names(parsed))
    callees = {c.callee_name for c in parsed.calls}
    assert "printf" in callees
    assert "format_name" in callees
    classes = {c.name for c in parsed.classes}
    assert "Greeter" in classes
    modules = {imp.module for imp in parsed.imports}
    assert "stdio.h" in modules
    assert "helper.h" in modules


def test_cpp_parser_class_and_namespace():
    src = b'''
#include <string>
#include <vector>
using std::string;

namespace greet {
    class Greeter {
    public:
        explicit Greeter(string name);
        string greet() const;
    private:
        string name_;
    };

    Greeter::Greeter(string name) : name_(std::move(name)) {}

    string Greeter::greet() const {
        return std::string("hello, ") + name_;
    }
}
'''
    parser = get_parser("cpp")
    assert parser is not None
    parsed = parser.parse(Path("greeter.cpp"), src)
    assert parsed.language == "cpp"
    classes = {c.name for c in parsed.classes}
    assert "Greeter" in classes
    fnames = _names(parsed)
    assert "greet" in fnames
    # Out-of-line definitions should be picked up; constructor name extraction
    # in the cpp grammar is best-effort but the body should be parsed for calls.
    callees = {c.callee_name for c in parsed.calls}
    assert "move" in callees or "string" in callees
    modules = {imp.module for imp in parsed.imports}
    assert any("string" in m for m in modules)

"""Sanity tests for the Phase-2 language parsers.

These confirm that each parser registers itself, returns the right
language label, and extracts at least one function + one import from a
minimal sample. Deeper grammar coverage will land alongside the LSP
integration in Phase 3.
"""

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


def test_rust_parser():
    src = b'''
use std::collections::HashMap;

struct Greeter { name: String }

impl Greeter {
    fn new(name: String) -> Self { Self { name } }
    async fn greet(&self) -> String {
        format(&self.name)
    }
}

fn format(name: &str) -> String { format!("hello, {}", name) }
'''
    parser = get_parser("rust")
    assert parser is not None
    parsed = parser.parse(Path("greeter.rs"), src)
    assert parsed.language == "rust"
    assert "format" in _names(parsed)
    assert "greet" in _names(parsed)
    greet = next(fn for fn in parsed.functions if fn.name == "greet")
    assert greet.is_async is True
    callees = {c.callee_name for c in parsed.calls}
    assert "format" in callees
    modules = {imp.module for imp in parsed.imports}
    assert any("HashMap" in m for m in modules)


def test_go_parser():
    src = b'''
package greeter

import (
    "fmt"
    "strings"
)

type Greeter struct { Name string }

func (g *Greeter) Greet() string {
    return fmt.Sprintf("hello, %s", strings.ToLower(g.Name))
}

func New(name string) *Greeter { return &Greeter{Name: name} }
'''
    parser = get_parser("go")
    assert parser is not None
    parsed = parser.parse(Path("greeter.go"), src)
    assert parsed.language == "go"
    assert {"Greet", "New"}.issubset(_names(parsed))
    callees = {c.callee_name for c in parsed.calls}
    # Selector-call extracts the trailing name
    assert "Sprintf" in callees
    assert "ToLower" in callees
    modules = {imp.module for imp in parsed.imports}
    assert "fmt" in modules
    assert "strings" in modules


def test_java_parser():
    src = b'''
package com.example.greeter;

import java.util.List;

public class Greeter {
    private final String name;

    public Greeter(String name) { this.name = name; }

    public String greet() {
        return format(this.name);
    }

    private String format(String n) { return "hello, " + n; }
}
'''
    parser = get_parser("java")
    assert parser is not None
    parsed = parser.parse(Path("Greeter.java"), src)
    assert parsed.language == "java"
    assert {"greet", "format"}.issubset(_names(parsed))
    callees = {c.callee_name for c in parsed.calls}
    assert "format" in callees
    classes = {c.name for c in parsed.classes}
    assert "Greeter" in classes
    modules = {imp.module for imp in parsed.imports}
    assert "java.util.List" in modules


def test_ruby_parser():
    src = b'''
require "json"
require_relative "helper"

class Greeter
  def initialize(name)
    @name = name
  end

  def greet
    Formatter.run(@name)
  end
end
'''
    parser = get_parser("ruby")
    assert parser is not None
    parsed = parser.parse(Path("greeter.rb"), src)
    assert parsed.language == "ruby"
    assert {"initialize", "greet"}.issubset(_names(parsed))
    callees = {c.callee_name for c in parsed.calls}
    assert "run" in callees
    classes = {c.name for c in parsed.classes}
    assert "Greeter" in classes
    modules = {imp.module for imp in parsed.imports}
    assert "json" in modules
    assert "helper" in modules

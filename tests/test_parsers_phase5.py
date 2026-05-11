"""Sanity tests for the Phase-5 parser fleet.

Each test asserts that the parser registers and that it can return *something*
(at minimum one function or one import) from a representative source.
Grammar-specific structural assertions live in their own files.
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


def _has_lang(lang: str) -> bool:
    try:
        get_language(lang)
        return True
    except Exception:
        return False


def _names(parsed) -> set[str]:
    return {fn.name for fn in parsed.functions}


def _classes(parsed) -> set[str]:
    return {c.name for c in parsed.classes}


@pytest.mark.skipif(not _has_lang("csharp"), reason="csharp grammar missing")
def test_csharp():
    src = b'''
namespace App {
    using System;
    public class Greeter {
        public string Greet(string name) { return Format(name); }
        private string Format(string n) { return "hi " + n; }
    }
}
'''
    p = get_parser("csharp")
    parsed = p.parse(Path("Greeter.cs"), src)
    assert "Greet" in _names(parsed)
    assert "Greeter" in _classes(parsed)


@pytest.mark.skipif(not _has_lang("kotlin"), reason="kotlin grammar missing")
def test_kotlin():
    src = b'''
package com.example

import kotlinx.coroutines.delay

class Greeter(val name: String) {
    suspend fun greet(): String { return "hi $name" }
}
'''
    p = get_parser("kotlin")
    parsed = p.parse(Path("Greeter.kt"), src)
    assert "greet" in _names(parsed)
    assert "Greeter" in _classes(parsed)


@pytest.mark.skipif(not _has_lang("scala"), reason="scala grammar missing")
def test_scala():
    src = b'''
package greet

import scala.collection.mutable

class Greeter(name: String) {
  def greet: String = format(name)
  private def format(n: String): String = s"hi $n"
}
'''
    p = get_parser("scala")
    parsed = p.parse(Path("Greeter.scala"), src)
    assert {"greet", "format"}.issubset(_names(parsed))


@pytest.mark.skipif(not _has_lang("php"), reason="php grammar missing")
def test_php():
    src = b'''<?php
namespace App;
use App\\Helpers;

class Greeter {
    public function greet(string $name): string {
        return Helpers::fmt($name);
    }
}
'''
    p = get_parser("php")
    parsed = p.parse(Path("Greeter.php"), src)
    assert "Greeter" in _classes(parsed)
    assert "greet" in _names(parsed)


@pytest.mark.skipif(not _has_lang("solidity"), reason="solidity grammar missing")
def test_solidity():
    src = b'''
pragma solidity ^0.8.0;

import "./Counter.sol";

contract Greeter {
    string public name;
    constructor(string memory n) { name = n; }
    function greet() external view returns (string memory) {
        return name;
    }
}
'''
    p = get_parser("solidity")
    parsed = p.parse(Path("Greeter.sol"), src)
    assert "Greeter" in _classes(parsed)
    assert "greet" in _names(parsed)


@pytest.mark.skipif(not _has_lang("lua"), reason="lua grammar missing")
def test_lua():
    src = b'''
local M = require "helpers"

function greet(name)
    return M.fmt(name)
end
'''
    p = get_parser("lua")
    parsed = p.parse(Path("greet.lua"), src)
    assert "greet" in _names(parsed)
    mods = {imp.module for imp in parsed.imports}
    assert "helpers" in mods

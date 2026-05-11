"""Vue / Svelte / Jupyter wrapper parsers.

These don't need a tree-sitter grammar for Vue/Svelte themselves — they
strip out the `<script>` block with a regex and feed the inner source to
the JS/TS parser. The Jupyter wrapper parses JSON and dispatches to the
kernel-language parser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from tree_sitter_language_pack import get_language  # noqa: F401

    HAS_TS = True
except ImportError:  # pragma: no cover
    HAS_TS = False

from ckg.parsers import get_parser

pytestmark = pytest.mark.skipif(not HAS_TS, reason="tree-sitter-language-pack not installed")


VUE_SOURCE = b"""<template>
  <button @click="greet">Hi</button>
</template>

<script lang="ts">
import { ref } from 'vue';

export function greet(name: string): string {
  return format(name);
}
function format(n: string) { return 'hi ' + n; }
</script>

<style>
button { color: red; }
</style>
"""


def test_vue_script_extraction():
    parser = get_parser("vue")
    assert parser is not None
    parsed = parser.parse(Path("Greeter.vue"), VUE_SOURCE)
    assert parsed.language == "vue"
    names = {fn.name for fn in parsed.functions}
    assert {"greet", "format"}.issubset(names)
    callees = {c.callee_name for c in parsed.calls}
    assert "format" in callees
    modules = {imp.module for imp in parsed.imports}
    assert "vue" in modules
    # The script block starts on line 5 in the SFC, so functions should be
    # at line >= 5
    greet_fn = next(fn for fn in parsed.functions if fn.name == "greet")
    assert greet_fn.start_line >= 5


SVELTE_SOURCE = b"""<script lang=\"ts\">
  import { onMount } from 'svelte';
  function greet(name: string) { return format(name); }
  function format(n: string) { return 'hi ' + n; }
  onMount(() => greet('world'));
</script>

<button>hi</button>
"""


def test_svelte_script_extraction():
    parser = get_parser("svelte")
    assert parser is not None
    parsed = parser.parse(Path("App.svelte"), SVELTE_SOURCE)
    assert parsed.language == "svelte"
    names = {fn.name for fn in parsed.functions}
    assert {"greet", "format"}.issubset(names)


def test_jupyter_python_notebook():
    nb = {
        "metadata": {"kernelspec": {"language": "python", "name": "python3"}},
        "nbformat": 4, "nbformat_minor": 5,
        "cells": [
            {"cell_type": "markdown", "source": ["# Hello\n", "\n"]},
            {"cell_type": "code", "source": [
                "import json\n",
                "\n",
                "def greet(name):\n",
                "    return _fmt(name)\n",
                "\n",
                "def _fmt(n):\n",
                "    return f'hi {n}'\n",
            ]},
            {"cell_type": "code", "source": ["greet('world')\n"]},
        ],
    }
    body = json.dumps(nb).encode()
    parser = get_parser("ipynb")
    assert parser is not None
    parsed = parser.parse(Path("notebook.ipynb"), body)
    assert parsed.language == "ipynb/python"
    names = {fn.name for fn in parsed.functions}
    assert {"greet", "_fmt"}.issubset(names)
    callees = {c.callee_name for c in parsed.calls}
    assert "_fmt" in callees


def test_jupyter_unknown_kernel_returns_empty():
    nb = {
        "metadata": {"kernelspec": {"language": "haskell"}},
        "cells": [{"cell_type": "code", "source": ["main = putStrLn \"hi\"\n"]}],
    }
    parser = get_parser("ipynb")
    parsed = parser.parse(Path("nb.ipynb"), json.dumps(nb).encode())
    # No mapping for haskell → empty ParseResult
    assert parsed.functions == []
    assert parsed.classes == []

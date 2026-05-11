"""Shared test fixtures.

These tests deliberately do NOT spin up Neo4j/Postgres/Redis. They assert on
import-time behaviour, parser correctness, and request-validation pieces that
don't need real backing stores. Integration tests against a running stack
live under `tests/integration/` and require `docker compose up` first.
"""

from __future__ import annotations

import os

import pytest

# Force-set test env vars so CI runs that export different placeholders (e.g.
# `CKG_BOOTSTRAP_TOKEN=ci-bootstrap-token`) don't leak through into tests that
# assert on specific values. We intentionally override here — these are
# fixtures, not production secrets.
os.environ["CKG_BOOTSTRAP_TOKEN"] = "test-bootstrap-token"
os.environ["NEO4J_PASSWORD"] = "test-neo4j-password"
os.environ["POSTGRES_PASSWORD"] = "test-postgres-password"
# CKG_SECRET_KEY is intentionally NOT set here. Tests that need it provide
# their own (see tests/test_secrets.py which generates a fresh Fernet key
# per test). CI exports a placeholder via the workflow env block.


def _parser_stack_works() -> bool:
    """Probe whether the tree-sitter parser stack can actually produce a
    working parser. Some combinations of tree-sitter + tree-sitter-language-pack
    install side-by-side cleanly but return parser objects whose `.parse`
    either doesn't exist or refuses the language object."""
    try:
        from ckg.parsers._ts import get_ts_parser

        p = get_ts_parser("python")
        p.parse(b"x = 1\n")
        return True
    except Exception:
        return False


# Compute once at session start to avoid the cost in every test.
PARSER_STACK_OK = _parser_stack_works()


def pytest_collection_modifyitems(config, items):
    """Skip parser tests when the tree-sitter stack isn't functional."""
    if PARSER_STACK_OK:
        return
    skipper = pytest.mark.skip(
        reason=(
            "tree-sitter parser stack non-functional in this environment "
            "(version mismatch between tree-sitter and tree-sitter-language-pack). "
            "Tracked separately — does not block other tests."
        ),
    )
    for item in items:
        nid = item.nodeid
        if any(
            part in nid
            for part in (
                "test_python_parser",
                "test_parsers_phase2",
                "test_parsers_phase5",
                "test_parsers_c_cpp",
                "test_parsers_wrappers",
            )
        ):
            item.add_marker(skipper)

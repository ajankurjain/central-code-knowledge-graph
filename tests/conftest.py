"""Shared test fixtures.

These tests deliberately do NOT spin up Neo4j/Postgres/Redis. They assert on
import-time behaviour, parser correctness, and request-validation pieces that
don't need real backing stores. Integration tests against a running stack
live under `tests/integration/` and require `docker compose up` first.
"""

from __future__ import annotations

import os

# Force-set test env vars so CI runs that export different placeholders (e.g.
# `CKG_BOOTSTRAP_TOKEN=ci-bootstrap-token`) don't leak through into tests that
# assert on specific values. We intentionally override here — these are
# fixtures, not production secrets.
os.environ["CKG_BOOTSTRAP_TOKEN"] = "test-bootstrap-token"
os.environ["NEO4J_PASSWORD"] = "test-neo4j-password"
os.environ["POSTGRES_PASSWORD"] = "test-postgres-password"
# Valid Fernet key (32-byte url-safe base64) for tests that exercise the
# secrets module without going through tests/test_secrets.py's own setup.
os.environ.setdefault(
    "CKG_SECRET_KEY", "Y2lmZXJuZXRfa2V5X3BsZWFzZV9yb3RhdGVfMzJfYnl0ZXM="
)

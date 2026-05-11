"""Shared test fixtures.

These tests deliberately do NOT spin up Neo4j/Postgres/Redis. They assert on
import-time behaviour, parser correctness, and request-validation pieces that
don't need real backing stores. Integration tests against a running stack
live under `tests/integration/` and require `docker compose up` first.
"""

from __future__ import annotations

import os

# Make the Settings constructor happy without a real .env present
os.environ.setdefault("CKG_BOOTSTRAP_TOKEN", "test-bootstrap-token")
os.environ.setdefault("NEO4J_PASSWORD", "test-neo4j-password")
os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-password")

"""Neo4j driver + schema bootstrap."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase

from ckg.config import get_settings
from ckg.logging import get_logger

log = get_logger(__name__)

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = GraphDatabase.driver(
            s.neo4j_uri,
            auth=(s.neo4j_user, s.neo4j_password),
            max_connection_lifetime=300,
        )
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


@contextmanager
def session():
    s = get_settings()
    drv = get_driver()
    with drv.session(database=s.neo4j_database) as sess:
        yield sess


# ── Schema ──────────────────────────────────────────────────────────────────
#
# Node labels
#   Repo                 { id, name, url, default_branch, last_indexed_at }
#   File                 { repo_id, path, language, sha, size_bytes, last_modified }
#   Class                { repo_id, file_path, name, qualified_name, start_line, end_line }
#   Function             { repo_id, file_path, name, qualified_name, start_line, end_line,
#                          is_method, is_async, doc, body_sha, embedding (vector) }
#   Module               { repo_id, name }
#
# Relationships
#   (Repo)-[:CONTAINS]->(File)
#   (File)-[:DEFINES]->(Class|Function)
#   (Class)-[:HAS_METHOD]->(Function)
#   (Function)-[:CALLS {via?}]->(Function)
#   (File)-[:IMPORTS]->(Module|File)
#   (Function)-[:TESTS]->(Function)         (heuristic, post-process)
# ────────────────────────────────────────────────────────────────────────────


SCHEMA_STATEMENTS: list[str] = [
    # Uniqueness constraints (also create btree indexes)
    "CREATE CONSTRAINT repo_id IF NOT EXISTS FOR (r:Repo) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT file_id IF NOT EXISTS FOR (f:File) REQUIRE (f.repo_id, f.path) IS UNIQUE",
    "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (c:Class) REQUIRE (c.repo_id, c.qualified_name) IS UNIQUE",
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE (fn.repo_id, fn.qualified_name) IS UNIQUE",
    "CREATE CONSTRAINT module_id IF NOT EXISTS FOR (m:Module) REQUIRE (m.repo_id, m.name) IS UNIQUE",
    # CallSite nodes are owned by their caller, identified by (caller, callee_name, line).
    # We keep them around between ingests so incremental updates only have to refresh
    # the changed files (Phase 2).
    "CREATE CONSTRAINT call_site_id IF NOT EXISTS FOR (cs:CallSite) REQUIRE (cs.repo_id, cs.caller_qname, cs.callee_name, cs.line) IS UNIQUE",
    # Architecture-analysis outputs (Phase 6) — clusters of files and design-smell warnings.
    "CREATE CONSTRAINT cluster_id IF NOT EXISTS FOR (cl:Cluster) REQUIRE (cl.repo_id, cl.id) IS UNIQUE",
    "CREATE CONSTRAINT warning_id IF NOT EXISTS FOR (w:Warning) REQUIRE (w.repo_id, w.kind, w.target_kind, w.target_id) IS UNIQUE",

    # Lookup indexes
    "CREATE INDEX file_language IF NOT EXISTS FOR (f:File) ON (f.language)",
    "CREATE INDEX file_sha IF NOT EXISTS FOR (f:File) ON (f.sha)",
    "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
    "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
    "CREATE INDEX warning_severity IF NOT EXISTS FOR (w:Warning) ON (w.severity)",

    # Full-text indexes
    "CREATE FULLTEXT INDEX fn_text IF NOT EXISTS FOR (fn:Function) ON EACH [fn.name, fn.qualified_name, fn.doc]",
    "CREATE FULLTEXT INDEX cls_text IF NOT EXISTS FOR (c:Class) ON EACH [c.name, c.qualified_name]",
    "CREATE FULLTEXT INDEX file_text IF NOT EXISTS FOR (f:File) ON EACH [f.path]",
]


def vector_index_statements(dim: int) -> Iterable[str]:
    """Vector index (Neo4j 5.13+). Created separately since it needs the dim."""
    return [
        f"""CREATE VECTOR INDEX function_embedding IF NOT EXISTS
        FOR (fn:Function) ON fn.embedding
        OPTIONS {{ indexConfig: {{
          `vector.dimensions`: {dim},
          `vector.similarity_function`: 'cosine'
        }} }}"""
    ]


def init_schema() -> None:
    """Idempotently apply the graph schema."""
    s = get_settings()
    with session() as sess:
        for stmt in SCHEMA_STATEMENTS:
            sess.run(stmt)
        for stmt in vector_index_statements(s.embedding_dim):
            try:
                sess.run(stmt)
            except Exception as exc:  # pragma: no cover
                log.warning("vector_index_skip", error=str(exc))
    log.info("neo4j_schema_ready")


def ping() -> bool:
    try:
        with session() as sess:
            sess.run("RETURN 1").consume()
        return True
    except Exception as exc:
        log.warning("neo4j_ping_failed", error=str(exc))
        return False

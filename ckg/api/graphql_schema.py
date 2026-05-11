"""Strawberry GraphQL schema.

Mirrors the REST surface — same queries, same auth (the FastAPI dependency
runs before the GraphQL router resolves a request). Mount at /v1/graphql.

Open the GraphiQL UI at http://localhost:8080/v1/graphql in a browser.
"""

from __future__ import annotations

from typing import Optional

import strawberry

from ckg.db.neo4j import session as neo_session


# ── Types ───────────────────────────────────────────────────────────────────


@strawberry.type
class Stats:
    nodes: int
    edges: int
    repos: int
    files: int


@strawberry.type
class FunctionRef:
    repo_id: str
    qualified_name: str
    file_path: str
    line: int


@strawberry.type
class SearchHit:
    repo_id: str
    qualified_name: str
    file_path: str
    line: int
    score: float
    kind: Optional[str] = None


@strawberry.type
class ImportEntry:
    name: str
    labels: list[str]


@strawberry.type
class FileSymbols:
    repo_id: str
    path: str
    language: str | None
    size_bytes: int | None
    classes: list["ClassRef"]
    functions: list["FunctionRef2"]


@strawberry.type
class ClassRef:
    name: str
    qualified_name: str
    start_line: int | None
    end_line: int | None


@strawberry.type
class FunctionRef2:
    name: str
    qualified_name: str
    start_line: int | None
    end_line: int | None
    is_async: bool | None


# ── Query root ──────────────────────────────────────────────────────────────


@strawberry.type
class Query:
    @strawberry.field
    def stats(self) -> Stats:
        with neo_session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()
            edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
            repos = s.run("MATCH (r:Repo) RETURN count(r) AS c").single()
            files = s.run("MATCH (f:File) RETURN count(f) AS c").single()
        return Stats(
            nodes=nodes["c"] if nodes else 0,
            edges=edges["c"] if edges else 0,
            repos=repos["c"] if repos else 0,
            files=files["c"] if files else 0,
        )

    @strawberry.field
    def callers_of(
        self,
        repo_id: str,
        qualified_name: str,
        depth: int = 1,
        limit: int = 100,
    ) -> list[FunctionRef]:
        cy = f"""
            MATCH (target:Function {{repo_id: $rid, qualified_name: $qn}})
            MATCH (caller:Function)-[:CALLS*1..{max(1, min(depth, 4))}]->(target)
            RETURN DISTINCT caller.qualified_name AS qn,
                            caller.file_path AS path,
                            caller.start_line AS line
            LIMIT $limit
        """
        with neo_session() as s:
            rows = s.run(cy, rid=repo_id, qn=qualified_name, limit=limit).data()
        return [FunctionRef(repo_id=repo_id, qualified_name=r["qn"], file_path=r["path"], line=r["line"] or 0) for r in rows]

    @strawberry.field
    def callees_of(
        self,
        repo_id: str,
        qualified_name: str,
        depth: int = 1,
        limit: int = 100,
    ) -> list[FunctionRef]:
        cy = f"""
            MATCH (source:Function {{repo_id: $rid, qualified_name: $qn}})
            MATCH (source)-[:CALLS*1..{max(1, min(depth, 4))}]->(callee:Function)
            RETURN DISTINCT callee.qualified_name AS qn,
                            callee.file_path AS path,
                            callee.start_line AS line
            LIMIT $limit
        """
        with neo_session() as s:
            rows = s.run(cy, rid=repo_id, qn=qualified_name, limit=limit).data()
        return [FunctionRef(repo_id=repo_id, qualified_name=r["qn"], file_path=r["path"], line=r["line"] or 0) for r in rows]

    @strawberry.field
    def imports_of(self, repo_id: str, path: str, limit: int = 200) -> list[ImportEntry]:
        cy = """
            MATCH (f:File {repo_id: $rid, path: $path})-[:IMPORTS]->(m)
            RETURN m.name AS name, labels(m) AS labels
            LIMIT $limit
        """
        with neo_session() as s:
            rows = s.run(cy, rid=repo_id, path=path, limit=limit).data()
        return [ImportEntry(name=r["name"], labels=r["labels"] or []) for r in rows]

    @strawberry.field
    def blast_radius(
        self,
        repo_id: str,
        path: str,
        depth: int = 2,
        limit: int = 500,
    ) -> list[str]:
        """Upstream callers — files affected by a change to `path`."""
        cy = f"""
            MATCH (src:File {{repo_id: $rid, path: $path}})
            MATCH (src)-[:DEFINES]->(target:Function)<-[:CALLS*1..{max(1, min(depth, 4))}]-(caller:Function)
            MATCH (caller_file:File)-[:DEFINES]->(caller)
            WHERE caller_file <> src
            RETURN DISTINCT caller_file.path AS path
            LIMIT $limit
        """
        with neo_session() as s:
            rows = s.run(cy, rid=repo_id, path=path, limit=limit).data()
        return [r["path"] for r in rows]

    @strawberry.field
    def downstream_dependencies(
        self,
        repo_id: str,
        path: str,
        depth: int = 2,
        limit: int = 500,
    ) -> list[str]:
        """Outgoing callees — files this file depends on."""
        cy = f"""
            MATCH (src:File {{repo_id: $rid, path: $path}})
            MATCH (src)-[:DEFINES]->(:Function)-[:CALLS*1..{max(1, min(depth, 4))}]->(target:Function)
            MATCH (target_file:File)-[:DEFINES]->(target)
            WHERE target_file <> src
            RETURN DISTINCT target_file.path AS path
            LIMIT $limit
        """
        with neo_session() as s:
            rows = s.run(cy, rid=repo_id, path=path, limit=limit).data()
        return [r["path"] for r in rows]

    @strawberry.field
    def file_overview(self, repo_id: str, path: str) -> FileSymbols | None:
        cy = """
            MATCH (f:File {repo_id: $rid, path: $path})
            OPTIONAL MATCH (f)-[:DEFINES]->(c:Class)
            OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function)
            RETURN
              f.language AS language,
              f.size_bytes AS size_bytes,
              collect(DISTINCT { name: c.name, qualified_name: c.qualified_name,
                                 start_line: c.start_line, end_line: c.end_line }) AS classes,
              collect(DISTINCT { name: fn.name, qualified_name: fn.qualified_name,
                                 start_line: fn.start_line, end_line: fn.end_line,
                                 is_async: fn.is_async }) AS functions
        """
        with neo_session() as s:
            row = s.run(cy, rid=repo_id, path=path).single()
        if not row:
            return None
        return FileSymbols(
            repo_id=repo_id, path=path,
            language=row["language"], size_bytes=row["size_bytes"],
            classes=[
                ClassRef(
                    name=c.get("name") or "?",
                    qualified_name=c.get("qualified_name") or "?",
                    start_line=c.get("start_line"),
                    end_line=c.get("end_line"),
                )
                for c in (row["classes"] or []) if c.get("name")
            ],
            functions=[
                FunctionRef2(
                    name=fn.get("name") or "?",
                    qualified_name=fn.get("qualified_name") or "?",
                    start_line=fn.get("start_line"),
                    end_line=fn.get("end_line"),
                    is_async=fn.get("is_async"),
                )
                for fn in (row["functions"] or []) if fn.get("name")
            ],
        )

    @strawberry.field
    def search_keyword(
        self,
        q: str,
        repo_id: Optional[str] = None,
        limit: int = 25,
    ) -> list[SearchHit]:
        where = "WHERE node.repo_id = $rid" if repo_id else ""
        cy = f"""
            CALL db.index.fulltext.queryNodes('fn_text', $q) YIELD node, score
            {where}
            RETURN node.repo_id AS repo_id,
                   node.qualified_name AS qualified_name,
                   node.file_path AS path,
                   node.start_line AS line,
                   labels(node)[0] AS kind,
                   score
            ORDER BY score DESC
            LIMIT $limit
        """
        params: dict = {"q": q, "limit": limit}
        if repo_id:
            params["rid"] = repo_id
        with neo_session() as s:
            rows = s.run(cy, **params).data()
        return [
            SearchHit(
                repo_id=r["repo_id"], qualified_name=r["qualified_name"],
                file_path=r["path"], line=r["line"] or 0, score=r["score"], kind=r["kind"],
            )
            for r in rows
        ]

    @strawberry.field
    def search_semantic(
        self,
        q: str,
        repo_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        from ckg.services.embeddings import embed_text  # lazy

        vec = embed_text(q).tolist()
        where = "WHERE node.repo_id = $rid" if repo_id else ""
        cy = f"""
            CALL db.index.vector.queryNodes('function_embedding', $limit, $vec)
            YIELD node, score
            {where}
            RETURN node.repo_id AS repo_id,
                   node.qualified_name AS qualified_name,
                   node.file_path AS path,
                   node.start_line AS line,
                   score
            ORDER BY score DESC
        """
        params: dict = {"vec": vec, "limit": limit}
        if repo_id:
            params["rid"] = repo_id
        with neo_session() as s:
            rows = s.run(cy, **params).data()
        return [
            SearchHit(
                repo_id=r["repo_id"], qualified_name=r["qualified_name"],
                file_path=r["path"], line=r["line"] or 0, score=r["score"],
            )
            for r in rows
        ]


schema = strawberry.Schema(query=Query)

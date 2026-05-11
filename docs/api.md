# API reference

Auto-generated OpenAPI: `http://localhost:8080/docs` (Swagger UI) or
`http://localhost:8080/openapi.json`.

This page summarizes the surface area.

## Authentication

Every endpoint outside `/healthz` and `/readyz` requires either:

- `Authorization: Bearer ckg_<token>`, or
- `X-API-Key: ckg_<token>`

The bootstrap token from `.env` has scope `admin` and is intended only to
mint the first real tokens. Rotate it after first use.

Scopes:

| Scope | Allows |
|---|---|
| `admin` | Everything (mint/revoke tokens). |
| `repo:write` | Register/delete repos, trigger ingest. |
| `repo:read` | List repos, query graph, search. |

## Endpoints

### System

- `GET /healthz` — liveness (always 200 if process is up).
- `GET /readyz` — readiness; per-store status.

### Tokens (admin)

- `POST /v1/tokens` — `{name, scopes}` → returns plaintext token **once**.
- `GET /v1/tokens` — list (without the raw values).
- `DELETE /v1/tokens/{id}` — revoke.

### Repos

- `POST /v1/repos` — register `{id, url, default_branch}` (`repo:write`).
- `GET /v1/repos` — list (`repo:read`).
- `GET /v1/repos/{id}` — fetch one (`repo:read`).
- `DELETE /v1/repos/{id}` — drop registration + sub-graph (`repo:write`).
- `POST /v1/repos/{id}/ingest` — enqueue full re-parse (`repo:write`).
- `GET /v1/repos/{id}/runs` — ingest run history (`repo:read`).

### Graph

- `GET /v1/graph/stats` — node/edge/repo/file counts.
- `GET /v1/graph/callers_of?repo_id=…&qualified_name=…&depth=1`
- `GET /v1/graph/callees_of?repo_id=…&qualified_name=…&depth=1`
- `GET /v1/graph/imports_of?repo_id=…&path=…`
- `GET /v1/graph/blast_radius?repo_id=…&path=…&depth=2` — files affected if this file changes (upstream callers).
- `GET /v1/graph/downstream_dependencies?repo_id=…&path=…&depth=2` — files this file depends on (outgoing callees).
- `GET /v1/graph/file?repo_id=…&path=…`

### Search

- `GET /v1/search/keyword?q=…&repo_id=…` — Lucene FTS.
- `GET /v1/search/semantic?q=…&repo_id=…` — vector cosine.

### MCP

- `POST /v1/mcp` — JSON-RPC 2.0. Methods: `initialize`, `tools/list`,
  `tools/call`. See [../integrations/cursor/README.md](../integrations/cursor/README.md)
  for the tool catalogue.

### GraphQL

- `POST /v1/graphql` — Strawberry GraphQL endpoint. Same bearer-token auth
  as the REST surface. Open the URL in a browser for the GraphiQL UI.

Example query:

```graphql
query {
  stats { nodes edges repos files }
  callersOf(repoId: "my-repo", qualifiedName: "my.module.foo", depth: 2) {
    qualifiedName
    filePath
    line
  }
  searchSemantic(q: "where do we parse Tree-sitter trees", limit: 5) {
    qualifiedName
    score
  }
}
```

Curl:

```bash
curl -sX POST -H "$H" -H 'content-type: application/json' \
  -d '{"query":"{ stats { nodes edges repos files } }"}' \
  http://localhost:8080/v1/graphql
```

## Quick curl recipes

```bash
T="ckg_YOUR_TOKEN_HERE"
H="Authorization: Bearer $T"

# Register a repo
curl -sX POST -H "$H" -H 'content-type: application/json' \
  -d '{"id":"my-repo","url":"file:///abs/path/to/repo","default_branch":"main"}' \
  http://localhost:8080/v1/repos

# Trigger ingest
curl -sX POST -H "$H" http://localhost:8080/v1/repos/my-repo/ingest

# Wait, then look up callers
curl -s -H "$H" \
  "http://localhost:8080/v1/graph/callers_of?repo_id=my-repo&qualified_name=my.module.foo&depth=2"

# Semantic search
curl -s -H "$H" \
  "http://localhost:8080/v1/search/semantic?q=parse+ingest+pipeline&repo_id=my-repo"
```

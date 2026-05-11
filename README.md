# central-code-knowledge-graph

> A **central, multi-repo code knowledge graph** for AI agents. Neo4j-backed,
> Tree-sitter parsing, full-text + vector search, MCP-ready. Drop-in for
> Cursor / VS Code / Claude Code.

One server that:

- ingests many repositories (not just one) and keeps them incrementally fresh
- stores them as a Neo4j property graph (`File`, `Class`, `Function`,
  `Module` + `CONTAINS`, `DEFINES`, `HAS_METHOD`, `CALLS`, `IMPORTS`)
- exposes **REST**, **MCP/JSON-RPC**, and a **`ckg` CLI**
- supports **structural** queries (callers, callees, imports, impact radius),
  **full-text** search, and **semantic** vector search
- secures every endpoint with **scoped API tokens** (argon2id-hashed)
- runs as a single `docker compose up`

## Why

| Need | How this server delivers |
|---|---|
| Rock-solid, won't fall over | Stateless API + workers; Neo4j/Postgres/Redis run with healthchecks + `restart: unless-stopped`; horizontal scale via `--scale worker=N` |
| Fast relationship search for AI agents | Native graph DB (Cypher) + Lucene FTS + vector index — all in Neo4j |
| Multi-language | Tree-sitter: **Python, JS/TS, Rust, Go, Java, Ruby, C, C++**. Pluggable — one file under `ckg/parsers/` adds another language |
| Precise cross-file edges | **Opt-in LSP pass** (`CKG_LSP_ENABLED=true`) upgrades CALLS edges with language-server-resolved targets. Pyright today; rust-analyzer / gopls / ts-server / jdtls planned. Graph stays functional with no LSP installed |
| Fast updates | **Incremental ingest** (`--incremental`): sha-diffs files against the graph, only re-parses what changed. Full reparse stays available as `--full` |
| Context for AI tools | Built-in MCP HTTP server → Cursor, VS Code, Claude Code drop in |
| Two query surfaces | REST (`/v1/*`) for simple calls + **GraphQL** (`/v1/graphql`) for composed traversals; both use the same API token |
| CLI for automation | `ckg` Typer CLI: register, ingest, query, search |
| Spec-driven | Auto-generated OpenAPI at `/docs`; GraphiQL UI at `/v1/graphql`; ADRs under `docs/adr/` |
| Whole-codebase index | One Neo4j graph spans all registered repos |
| Neo4j-backed | Functions, classes, files, imports, calls all stored as labeled nodes + typed relationships |
| Secure | API tokens with scopes (`admin`, `repo:write`, `repo:read`); hashed at rest |

## Architecture

```
                      ┌──────────────┐
   AI agents ───MCP──▶│              │
   CLI (ckg) ──REST──▶│   FastAPI    │──▶ Auth (API tokens, scopes)
   Web UI ────GQL───▶ │              │──▶ Audit log
                      └──────┬───────┘
                             │
            ┌────────────────┼─────────────────────────────┐
            ▼                ▼                             ▼
     ┌────────────┐   ┌─────────────┐              ┌───────────────┐
     │ Neo4j 5    │   │ Postgres    │              │ Redis         │
     │ graph +    │   │ repos +     │              │ cache + queue │
     │ vector +   │   │ tokens +    │              └───────┬───────┘
     │ FTS        │   │ runs +      │                      │
     └────────────┘   │ audit       │              ┌───────▼───────┐
                      └─────────────┘              │ Celery workers│
                                                   │  - clone      │
                                                   │  - parse      │
                                                   │  - embed      │
                                                   │  - write graph│
                                                   └───────┬───────┘
                                                           │
                                                   ┌───────▼───────┐
                                                   │ Tree-sitter   │
                                                   │ parsers       │
                                                   │ Py / JS / TS  │
                                                   │ (Rust/Ruby/   │
                                                   │  Go/Java soon)│
                                                   └───────────────┘
```

Full design rationale: [docs/adr/0001-architecture.md](docs/adr/0001-architecture.md).

## Quickstart

### 1. Prerequisites

- Docker Desktop (macOS / Windows) or Docker Engine + Compose v2 (Linux)
- 8 GB free RAM recommended
- Python 3.11+ on the host **only if** you want the CLI locally

### 2. Clone and configure

```bash
git clone https://github.com/ajankurjain/central-code-knowledge-graph.git
cd central-code-knowledge-graph
cp .env.example .env
```

Edit `.env` and replace every `change-me-*`. Generate strong values with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Start the stack

```bash
make up
```

(or `docker compose up -d`)

First boot is 1–3 minutes (image pulls + Neo4j schema init).

```bash
curl http://localhost:8080/readyz
# {"ready": true, "checks": {"neo4j": true, "postgres": true, "redis": true}, ...}
```

Open the auto-generated API docs: <http://localhost:8080/docs>

Open the web UI: <http://localhost:3000> (paste an API token to sign in).

### 4. Install the CLI

```bash
pip install -e .             # or: pipx install -e .
export CKG_SERVER=http://localhost:8080
ckg login --token "$(grep ^CKG_BOOTSTRAP_TOKEN .env | cut -d= -f2)"

# Mint a real token, then re-login with it:
ckg token create my-laptop --scope repo:read --scope repo:write
ckg login --token ckg_xxxxxxxxxxxxxxxxxxxx
```

### 5. Ingest your first repo

```bash
ckg repo register my-repo file:///Users/you/code/my-repo --branch main
ckg repo ingest    my-repo
ckg repo runs      my-repo          # watch progress
ckg graph stats
ckg search keyword "ingest pipeline"
ckg search semantic "where do we parse Tree-sitter trees?"
ckg graph callers my-repo my.module.foo --depth 2
```

### 5b. Or pull an entire org / group / workspace at once

Paste a single URL — GitHub org/user, GitLab group/user, Bitbucket
workspace, or a JSON/YAML manifest — and ckg discovers every accessible
repo, registers them, and queues a full ingest for each.

```bash
# Public org, anonymous
ckg source add https://github.com/orgs/anthropics

# Private org with a Personal Access Token (example: read from env)
export CKG_SOURCE_TOKEN="$GH_PAT"
ckg source add https://github.com/orgs/acme --include-forks

# GitLab group (incl. subgroups)
ckg source add https://gitlab.com/groups/gitlab-org

# Bitbucket workspace (token format: "username:app-password")
ckg source add https://bitbucket.org/atlassian --token "$BB_USER:$BB_APP_PASSWORD"

# Manifest URL (JSON or YAML list)
ckg source add https://example.com/all-repos.yaml

ckg source list          # see what you've added
ckg source repos 1       # repos discovered for source 1
ckg source sync 1        # re-discover; queues ingests for newly-added repos
ckg source delete 1 --yes  # CASCADE — drops every repo + graph data this source created
```

PATs are encrypted at rest with Fernet (key in `CKG_SECRET_KEY`). They
never appear in `repos.url` — the worker injects them into the clone
URL at fetch time.

### 6. Browse it in the UI

Open <http://localhost:3000>, paste an API token, and explore:

- **Dashboard** — node/edge/repo/file counts; repo list
- **Repos** — register repos, queue incremental or full ingests, watch run status
- **Sources** — paste a GitHub org / GitLab group / Bitbucket workspace / manifest URL and bulk-add every repo it exposes
- **Search** — keyword (Lucene FTS) or semantic (vector) across all (or one) repos
- **Graph** — force-directed call graph for any function, callers + callees up to depth 4

The UI is a static Next.js bundle served from the `web` container; the
browser hits the API directly using the bearer token kept in
`localStorage`.

### 7. Hook up your editor

| Editor | Guide |
|---|---|
| Cursor | [integrations/cursor/README.md](integrations/cursor/README.md) |
| VS Code (Copilot Chat / Cline / Roo Code) | [integrations/vscode/README.md](integrations/vscode/README.md) |
| Claude Code | [integrations/claude-code/README.md](integrations/claude-code/README.md) |

## What the graph looks like

```
(Repo)-[:CONTAINS]->(File)-[:DEFINES]->(Class)-[:HAS_METHOD]->(Function)
                          -[:DEFINES]->(Function)-[:CALLS]->(Function)
                          -[:IMPORTS]->(Module|File)
```

`Function` nodes carry a `embedding` vector property indexed for cosine
similarity. Names + docs feed Lucene full-text indexes. So one Cypher store
answers all three styles of query (structural / keyword / semantic).

## API surface (short)

Full reference: [docs/api.md](docs/api.md).

| Verb | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Readiness (per-store) |
| `POST` | `/v1/tokens` | Mint a token (admin) |
| `GET` | `/v1/tokens` | List tokens (admin) |
| `DELETE` | `/v1/tokens/{id}` | Revoke (admin) |
| `POST` | `/v1/repos` | Register a repo |
| `GET` | `/v1/repos` | List repos |
| `POST` | `/v1/repos/{id}/ingest` | Queue ingest |
| `GET` | `/v1/repos/{id}/runs` | Ingest history |
| `GET` | `/v1/graph/stats` | Graph counts |
| `GET` | `/v1/graph/callers_of` | Transitive callers |
| `GET` | `/v1/graph/callees_of` | Transitive callees |
| `GET` | `/v1/graph/imports_of` | Imports for a file |
| `GET` | `/v1/graph/impact_radius` | Blast radius for a file |
| `GET` | `/v1/graph/file` | Symbols in a file |
| `GET` | `/v1/search/keyword` | Lucene FTS |
| `GET` | `/v1/search/semantic` | Vector cosine |
| `POST` | `/v1/mcp` | MCP JSON-RPC for IDEs |
| `POST` | `/v1/graphql` | GraphQL endpoint (open in browser for GraphiQL UI) |

## Roadmap

- [x] **Phase 1** — Foundation, auth, Python/JS/TS ingest, REST + MCP, CLI
- [x] **Phase 2** — Incremental updates (per-file sha diff), GraphQL endpoint, Rust/Go/Java/Ruby parsers
- [x] **Phase 3** — C/C++ parsers; opt-in LSP precision pass (pyright today; rust-analyzer / gopls / ts-server / jdtls planned)
- [x] **Phase 4** — Next.js web UI: token login, dashboard, repo management, search (keyword + semantic), force-directed function call-graph viz
- [ ] **Phase 5** — Multi-tenant orgs/users, k8s/Helm, OpenTelemetry, Neo4j Causal Cluster

## Development

Backend:

```bash
pip install -e '.[dev]'
pytest -q
ruff check ckg
```

Web UI:

```bash
cd web
npm install --legacy-peer-deps
NEXT_PUBLIC_CKG_API=http://localhost:8080 npm run dev
# open http://localhost:3000
```

Project layout:

```
ckg/
├── api/        # FastAPI app + routes (REST + GraphQL + MCP)
├── auth.py     # API tokens, principal, scopes
├── cli/        # `ckg` Typer CLI
├── config.py   # Pydantic settings
├── db/         # neo4j / postgres / redis clients + schema
├── lsp/        # Opt-in LSP precision pass (Phase 3)
├── parsers/    # tree-sitter parsers, one per language
├── services/   # ingest, embeddings, lsp_resolve
└── worker/     # Celery app + tasks
web/            # Next.js 15 + Tailwind + react-force-graph-2d (Phase 4)
docker/         # API + worker + web Dockerfiles
docs/           # ADRs, deployment, API
integrations/   # cursor / vscode / claude-code MCP snippets
tests/          # pytest
```

## Security

- API tokens are 32-byte URL-safe random strings prefixed `ckg_`, **never**
  stored in plaintext — only argon2id hashes are persisted.
- The bootstrap token (`.env`) is your **only** way in on day 0; rotate it
  immediately after minting a scoped token.
- All non-health endpoints require a token; CORS is restricted to
  `CKG_CORS_ORIGINS`.
- `.env` is git-ignored. Do not commit it. Do not paste tokens into chats.

If you find a security issue, please open a private vulnerability report on
GitHub.

### Pre-commit credential audit

A small audit script refuses to commit credentials, IDE-assistant configs
(`.claude/`, `CLAUDE.md`, `.mcp.json`, `.cursor/`, `.continue/`, `.aider*`,
`.windsurf/`), or files matching common secret patterns (GitHub PAT,
OpenAI key, AWS access key, Slack token, JWT, PEM private key):

```bash
./scripts/audit-secrets.sh

# install as a git pre-commit hook (recommended):
ln -sf ../../scripts/audit-secrets.sh .git/hooks/pre-commit
```

## License

MIT — see [LICENSE](LICENSE).

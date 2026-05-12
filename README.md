<div align="center">

# central-code-knowledge-graph

**Stop re-reading. Start querying.**

AI coding tools re-read your entire codebase on every task. `ckg` fixes that. One server indexes every repo in your org with [Tree-sitter](https://tree-sitter.github.io/) across 26 languages, stores the structural map as a [Neo4j](https://neo4j.com/) property graph, keeps it fresh via incremental ingest + webhooks, and serves precise context to your AI assistant via [MCP](https://modelcontextprotocol.io/) so it reads only what matters.

[![PyPI](https://img.shields.io/pypi/v/central-code-knowledge-graph?label=pypi&color=2563eb&cacheSeconds=90)](https://pypi.org/project/central-code-knowledge-graph/)
[![CI](https://github.com/ajankurjain/central-code-knowledge-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/ajankurjain/central-code-knowledge-graph/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![Docker Compose](https://img.shields.io/badge/docker--compose-ready-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-008CC1?logo=neo4j&logoColor=white)](docker-compose.yml)
[![MCP](https://img.shields.io/badge/MCP-compatible-brightgreen)](integrations/cursor/README.md)
[![Languages](https://img.shields.io/badge/languages-26-blueviolet)](#supported-languages)
[![Tree-sitter](https://img.shields.io/badge/Tree--sitter-powered-orange)](https://tree-sitter.github.io/)

</div>

One server that:

- ingests many repositories (not just one) and keeps them incrementally fresh
- stores them as a Neo4j property graph (`File`, `Class`, `Function`,
  `Module` + `CONTAINS`, `DEFINES`, `HAS_METHOD`, `CALLS`, `IMPORTS`)
- exposes **REST**, **GraphQL**, **MCP/JSON-RPC**, and a **`ckg` CLI**
- supports **structural** queries (callers, callees, imports, blast radius,
  downstream dependencies), **full-text** search, and **semantic** vector search
- generates an **architecture map** with coupling warnings (cyclic deps, god
  modules, SDP violations) every ingest
- secures every endpoint with **scoped API tokens** (argon2id-hashed)
- runs as a single `docker compose up`

## Why

| Need | How this server delivers |
|---|---|
| Rock-solid, won't fall over | Stateless API + workers; Neo4j/Postgres/Redis run with healthchecks + `restart: unless-stopped`; horizontal scale via `--scale worker=N` |
| Fast relationship search for AI agents | Native graph DB (Cypher) + Lucene FTS + vector index — all in Neo4j |
| Multi-language | Tree-sitter parsers (23): **Python, JS/TS** (incl. JSX/TSX → React, Angular), **Rust, Go, Java, Ruby, C, C++, C#, Kotlin, Scala, Swift, PHP, Solidity, Dart, R, Perl, Lua, Zig, PowerShell, Julia, Nix**. Extraction wrappers (3): **Vue, Svelte** (delegates `<script>` to JS/TS), **Jupyter/Databricks `.ipynb`** (concatenates code cells, dispatches by kernel). Pluggable — one file under `ckg/parsers/` adds another language |
| Precise cross-file edges | **Opt-in LSP pass** (`CKG_LSP_ENABLED=true`) upgrades CALLS edges with language-server-resolved targets. Pyright today; rust-analyzer / gopls / ts-server / jdtls planned. Graph stays functional with no LSP installed |
| Fast updates | **Incremental ingest** (`--incremental`): sha-diffs files against the graph, only re-parses what changed. Full reparse stays available as `--full` |
| Context for AI tools | Built-in MCP HTTP server → Cursor, VS Code, Claude Code drop in |
| Two query surfaces | REST (`/v1/*`) for simple calls + **GraphQL** (`/v1/graphql`) for composed traversals; both use the same API token |
| CLI for automation | `ckg` Typer CLI: register, ingest, query, search |
| Spec-driven | Auto-generated OpenAPI at `/docs`; GraphiQL UI at `/v1/graphql`; ADRs under `docs/adr/` |
| Whole-codebase index | One Neo4j graph spans all registered repos |
| Neo4j-backed | Functions, classes, files, imports, calls all stored as labeled nodes + typed relationships |
| Secure | API tokens with scopes (`admin`, `repo:write`, `repo:read`); hashed at rest |

## Supported languages

**Tree-sitter parsers (23):** Python · JavaScript (incl. JSX → **React**) · TypeScript (incl. TSX → **Angular**) · Rust · Go · Java · Ruby · C · C++ · C# · Kotlin · Scala · Swift · PHP · Solidity · Dart · R · Perl · Lua · Zig · PowerShell · Julia · Nix

**Extraction wrappers (3):** **Vue** & **Svelte** SFCs (delegate `<script>` to JS/TS) · **Jupyter / Databricks** `.ipynb` (concatenate code cells, dispatch by kernel language)

Pluggable — adding another language is one file under `ckg/parsers/` and one line in the registry.

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

| | Required | Notes |
|---|---|---|
| Docker | **Docker Desktop** (macOS / Windows) or **Docker Engine + Compose v2** (Linux) | Must be **running** before step 3. Confirm with `docker info`. |
| RAM | 8 GB free | Neo4j wants 2 GB, sentence-transformers ~500 MB on first warmup |
| Disk | ~3 GB free | Base images (Neo4j, Postgres, Redis, Python, Node) total ~2 GB. Plus your repo clones under the `repo_data` volume. |
| Network | Outbound HTTPS | First boot pulls images from Docker Hub + npm + PyPI |
| Python | 3.11+ (host) | **Only** if you want to install the CLI on your laptop. Not needed otherwise — `make up` runs everything in containers. |

### 2. Clone and configure

```bash
git clone https://github.com/ajankurjain/central-code-knowledge-graph.git
cd central-code-knowledge-graph
cp .env.example .env
```

Replace every `change-me-*` in `.env` with strong randoms — the snippet below
generates a full, ready-to-go `.env` for local dev in one shot:

```bash
python3 - <<'PY'
import secrets, base64, os
subs = {
    "change-me-please-bootstrap-token": secrets.token_urlsafe(32),
    "change-me-please-fernet-key":     base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "change-me-neo4j-password":        secrets.token_urlsafe(24),
    "change-me-postgres-password":     secrets.token_urlsafe(24),
}
env = open(".env").read()
for k, v in subs.items():
    env = env.replace(k, v)
open(".env", "w").write(env)
PY
chmod 600 .env
```

> ⚠️  Keep `.env` out of git — it's already in `.gitignore`, the pre-commit
> hook (`scripts/audit-secrets.sh`) refuses any commit that contains it.

### 3. Start the stack

Make sure Docker Desktop is running first (`docker info` should succeed), then:

```bash
make up
# or: docker compose up -d --build
```

**First boot takes 5–10 minutes** — it pulls ~2 GB of base images and builds
the api / worker / web / beat images locally. Subsequent `make up` runs are
~10 seconds.

Confirm everything came up healthy:

```bash
docker compose ps
# all containers should show "running" and (healthy):
# ckg-api-1, ckg-beat-1, ckg-neo4j-1, ckg-postgres-1, ckg-redis-1, ckg-web-1, ckg-worker-1
```

Health check from outside:

```bash
curl http://localhost:8080/readyz
# {"ready":true,"checks":{"neo4j":true,"postgres":true,"redis":true},"version":"0.1.3"}
```

URLs:

| Service | URL |
|---|---|
| **Web UI** | <http://localhost:3000> |
| API (Swagger UI) | <http://localhost:8080/docs> |
| GraphQL (GraphiQL) | <http://localhost:8080/v1/graphql> |
| Neo4j Browser | <http://localhost:7474> (login `neo4j` / value of `NEO4J_PASSWORD` from `.env`) |
| Postgres | `localhost:5433` (mapped off default port to avoid clashes) |
| Redis | `localhost:6379` |

### 4. Sign in

Grab the **bootstrap token** from `.env`:

```bash
grep ^CKG_BOOTSTRAP_TOKEN .env | cut -d= -f2-
```

Then either:

**a) Use the web UI** — open <http://localhost:3000/login>, paste the token,
click **Sign in**. The Dashboard lights up.

**b) Use the `ckg` CLI**:

```bash
# From PyPI (light install — CLI only, talks to the Docker server):
pip install central-code-knowledge-graph

# Or pipx for an isolated install:
pipx install central-code-knowledge-graph

# Or editable install from a checkout for development:
pip install -e '.[dev]'

# Then:
export CKG_SERVER=http://localhost:8080
ckg login --token "$(grep ^CKG_BOOTSTRAP_TOKEN .env | cut -d= -f2-)"
ckg status        # should print graph counts
```

The bootstrap token has `admin` scope and is meant for one-time setup —
**mint a scoped token and use that going forward**:

```bash
ckg token create my-laptop --scope repo:read --scope repo:write
# copy the printed `ckg_…` token, then:
ckg login --token ckg_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 5. Ingest your first repo

```bash
# Pick a local repo to index. `file:///abs/path` clones-in-place, no network.
ckg repo register my-repo file:///Users/you/code/my-repo --branch main

# Run a full ingest.
ckg repo ingest    my-repo --full
ckg repo runs      my-repo                 # watch progress; a small repo finishes in seconds

# Verify the graph populated.
ckg graph stats
# → {"nodes": 3288, "edges": 6676, "repos": 1, "files": 80}  (example)

# Search.
ckg search keyword  "ingest pipeline"
ckg search semantic "where do we parse Tree-sitter trees?"

# Structural queries.
ckg graph callers    my-repo my.module.foo --depth 2
ckg graph blast      my-repo src/foo/bar.py        # files that break if bar.py changes
ckg graph downstream my-repo src/foo/bar.py        # files bar.py depends on
```

You can do the same from the web UI under **Repos** → **Register** → fill the
form, then click **ingest Δ** or **full reparse**. Watch progress on the repo
detail page (auto-refreshes while a run is in flight).

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

### 5c. Keep the graph fresh — polling + webhooks

Two ways to keep ingested repos up-to-date without manual triggers.
**Polling** uses a Celery Beat scheduler (one extra Compose service);
**webhooks** are push-driven by GitHub / GitLab / Bitbucket.

```bash
# Polling
ckg source schedule 1 30m       # re-discover source 1 every 30 minutes
ckg repo   poll     my-repo 5m  # incremental ingest of my-repo every 5 minutes

# Webhooks (returns the secret + receiver URL — paste both into the provider)
ckg source webhook  1 --enable
```

Provider setup:

| Provider | Where | Field |
|---|---|---|
| GitHub | repo / org Settings → Webhooks | `Payload URL` = `<your-server>/v1/webhooks/<source_id>`; `Content type: application/json`; `Secret` = the printed value; tick **just** the `push` event |
| GitLab | project Settings → Webhooks | `URL` = same as above; `Secret token` = the printed value; tick **Push events** |
| Bitbucket | workspace Webhooks → Add | `URL` = `<your-server>/v1/webhooks/<source_id>?secret=<paste>`; trigger on **Repository push** |

GitHub uses HMAC-SHA256 of the body, GitLab a shared-token header,
Bitbucket Cloud the URL-embedded secret. The same `/v1/webhooks/<id>`
endpoint detects the provider from headers automatically.

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

### Day-2 operations

```bash
make logs                 # tail every service
make restart              # restart api + worker only
docker compose stop       # park everything; data volumes persist
make up                   # bring it back
make clean                # WARNING: removes volumes — wipes graph + Postgres
make psql                 # psql shell inside the postgres container
make neo4j-shell          # cypher-shell inside the neo4j container
```

### Troubleshooting

Things that bit me during local setup — keep this open the first time you run.

| Symptom | Diagnosis / fix |
|---|---|
| `docker: command not found` | Docker Desktop isn't on PATH. macOS shortcut: `export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"`. |
| `docker info` fails / "Cannot connect to the Docker daemon" | Docker Desktop is installed but not running. Launch the Docker app and wait ~10s. |
| `make up` errors with `neo4j password required` | You skipped step 2 — `.env` doesn't exist (or still has `change-me-*` placeholders for the strict-required vars). Re-run the Python one-liner in step 2. |
| `ckg-web-1` stays in **Created** state and never starts | The image was never built. Run `docker compose build web && docker compose up -d web`. |
| `ckg-neo4j-1` flaps **Restarting** with `Unrecognized setting. No declared setting with name: PASSWORD` | Old compose file. Pull main — fixed in v0.1.1 by renaming the healthcheck env vars to `CKG_HEALTHCHECK_*`. |
| API container loops with `TypeError: APIRouter.__init__() got an unexpected keyword argument 'graphiql'` | strawberry-graphql renamed the arg. Fixed in v0.1.1. Pull main. |
| Worker / beat crash with `exec: "celery": executable file not found in $PATH` | Dockerfile didn't install `[server]` extras. Fixed in v0.1.1. Pull main + `docker compose build --no-cache worker beat`. |
| Ingest reports `files_skipped` for every file, `files_parsed: 0` | tree-sitter-language-pack 1.x compatibility issue. Fixed in v0.1.1 by pinning to 0.7-0.9. Pull main + rebuild api/worker. |
| GitHub README badge stuck on a stale version | GitHub's camo proxy caches images by URL. Bump the URL slightly (e.g. change `cacheSeconds=N` to a different N) to force a refetch. |
| Forgot the bootstrap token | `grep ^CKG_BOOTSTRAP_TOKEN .env \| cut -d= -f2-` |
| Want to wipe the graph and start over | `make clean && make up && python … (regenerate .env)`. Note: this also drops the Postgres data, so all minted tokens go too. |
| Forgot which port is which | All ports are configurable via `.env` (`CKG_API_PORT`, `CKG_WEB_PORT`). Defaults: 8080 / 3000 / 7474 (Neo4j) / 5433 (Postgres) / 6379 (Redis). |
| Run integration tests against the live stack | `docker compose exec api pytest tests/integration/ -q` (after `make up`). |

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
| `GET` | `/v1/graph/blast_radius` | Files affected if this file changes (upstream callers) |
| `GET` | `/v1/graph/downstream_dependencies` | Files this file depends on (outgoing callees) |
| `GET` | `/v1/graph/file` | Symbols in a file |
| `GET` | `/v1/search/keyword` | Lucene FTS |
| `GET` | `/v1/search/semantic` | Vector cosine |
| `POST` | `/v1/mcp` | MCP JSON-RPC for IDEs |
| `POST` | `/v1/graphql` | GraphQL endpoint (open in browser for GraphiQL UI) |

## Releases

Current: **v0.1.3** on [PyPI](https://pypi.org/project/central-code-knowledge-graph/) ·
full notes at [Releases](https://github.com/ajankurjain/central-code-knowledge-graph/releases).

| Version | Highlights |
|---|---|
| **v0.1.3** | Self-hosted GitLab support (`gitlab_instance` kind + bring-your-own-base-URL). Worker now scrubs `<scheme>://user:pw@…` userinfo and bare GitHub / GitLab PAT shapes before persisting clone errors, so a failed `git clone https://oauth2:glpat-…@host/path` no longer leaks the token into `ingest_runs.error`. `credentialed_clone_url_for_repo` falls back to a host-aware token injector when the source's `kind` is unknown to the running worker. Per-source live progress bar on `/sources` driven by a new `GET /v1/sources/{id}/progress` endpoint (indexed / queued / running / failed counts + last-sync / last-ingest timestamps + 5 s auto-poll while in flight). New `ckg.reconcile_stuck_ingests` beat task every 60 s — re-publishes orphaned `queued` rows (DB-vs-broker desync) and reaps zombie `running` rows so the progress bar never silently freezes. Searchable repo combobox on `/repos`, `/arch`, `/graph` with `INDEXED` / `NOT INDEXED` badges + refresh icon. Dashboard and `/repos` table now paginated (10 / 25 per page) with id / url / language filter. `/graph` shows top-20 most-connected functions as click-to-fill entry points when no qname is set — backed by `GET /v1/graph/entry_points` — plus a back-to-functions button. `tree-sitter>=0.25.2,<0.26` (csharp grammar v15 ABI). `python` parser detects `async` either as the node type OR as a child keyword. `lua` parser covers modern (`function_declaration`, `local_function`) and legacy node types. |
| **v0.1.2** | Per-repo PAT for cloning private repos (`POST /v1/repos {token}` + `PUT …/credentials` + Credentials panel in the web UI + `ckg repo register --token` / `ckg repo credentials`). Idempotent `ADD COLUMN IF NOT EXISTS` migration so existing installs pick up new columns on restart. Per-row ingest feedback on the /repos page. Runs-table error column now collapsible with full text. Web register form auto-slugifies with live preview. `tree-sitter>=0.24,<0.25` (csharp grammar v15). |
| **v0.1.1** | Live-verified runtime fixes: Dockerfile installs `[server]` extras so `celery` is on the worker's PATH; Neo4j healthcheck creds exposed via `CKG_HEALTHCHECK_*` (was conflicting with Neo4j's `NEO4J_*`-as-setting parsing); strawberry-graphql `graphql_ide=` arg compatibility; `tree-sitter-language-pack` pinned to the 0.x line where the parser objects still expose `.parse()`. |
| **v0.1.0** | Initial release. |

Upgrade:

```bash
pip install --upgrade central-code-knowledge-graph
# or, in a Docker checkout:
git pull && make build && make restart
```

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

# Deployment

This guide takes you from a clean machine to a running stack.

## Prerequisites

- **Docker Desktop** (macOS / Windows) or **Docker Engine + Compose v2** (Linux).
  - macOS: download from <https://www.docker.com/products/docker-desktop/>.
  - Linux: `curl -fsSL https://get.docker.com | sh` then `sudo apt install docker-compose-plugin`.
- **Git** (for cloning this repo and the repos you'll index).
- **8 GB free RAM** recommended (Neo4j wants 2 GB, sentence-transformers ~500 MB on first warmup).

## 1. Clone and configure

```bash
git clone https://github.com/ajankurjain/central-code-knowledge-graph.git
cd central-code-knowledge-graph
cp .env.example .env
```

Edit `.env` and replace every `change-me-*` value. Generate strong values:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # for CKG_BOOTSTRAP_TOKEN
python -c "import secrets; print(secrets.token_urlsafe(24))"   # for NEO4J_PASSWORD / POSTGRES_PASSWORD
```

> ⚠️ Treat `.env` like a credential. It is in `.gitignore` — keep it that way.

## 2. Bring the stack up

```bash
make up
# or:  docker compose up -d
```

First boot takes 1–3 minutes (image pulls + Neo4j schema init). Check progress:

```bash
make logs
```

Once healthy:

```bash
curl http://localhost:8080/readyz
# {"ready": true, "checks": {"neo4j": true, "postgres": true, "redis": true}, ...}
```

Useful ports:

| Service | URL |
|---|---|
| API | <http://localhost:8080> (OpenAPI at `/docs`) |
| Neo4j Browser | <http://localhost:7474> (login with `NEO4J_USER` / `NEO4J_PASSWORD`) |
| Postgres | `localhost:5433` (mapped off the default to avoid clashes) |
| Redis | `localhost:6379` |

## 3. Install the CLI (optional, host-side)

You can drive everything via `curl`, but the CLI is friendlier:

```bash
pip install -e .
# or for an isolated user install:
pipx install -e .
```

Tell the CLI where the server is and log in with the bootstrap token:

```bash
export CKG_SERVER=http://localhost:8080
ckg login --token "$(grep ^CKG_BOOTSTRAP_TOKEN .env | cut -d= -f2)"
```

Now mint a real, scoped token and use **that** going forward. Then revoke or
rotate the bootstrap token.

```bash
ckg token create my-laptop --scope repo:read --scope repo:write
# copy the printed token, then:
ckg login --token ckg_xxxxxxxxxxxxxxxxxxxx
```

## 4. Register and ingest your first repo

```bash
# A local clone:
ckg repo register submission-enterprise \
  file:///Users/you/code/submission-enterprise --branch main

# Or a remote:
ckg repo register submission-enterprise \
  https://github.com/yourorg/submission-enterprise.git --branch main

ckg repo ingest submission-enterprise
ckg repo runs   submission-enterprise        # watch progress
ckg graph stats
```

A first ingest of a ~10 kfile repo takes ~30–90 seconds.

## 5. Connect Cursor / VS Code / Claude Code

See:
- [../integrations/cursor/README.md](../integrations/cursor/README.md)
- [../integrations/vscode/README.md](../integrations/vscode/README.md)
- [../integrations/claude-code/README.md](../integrations/claude-code/README.md)

## Day-2 operations

| Task | How |
|---|---|
| View logs | `make logs` or `docker compose logs -f api worker` |
| Restart API/worker | `make restart` |
| Open Cypher shell | `make neo4j-shell` |
| Open psql | `make psql` |
| Rebuild images | `make build` |
| Wipe ALL data | `make clean` (deletes volumes — irreversible) |

### Backups

Neo4j data lives in the named volume `ckg_neo4j_data`. A simple offline backup:

```bash
docker compose stop neo4j
docker run --rm -v ckg_neo4j_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/neo4j-$(date +%F).tgz -C /data .
docker compose start neo4j
```

For Postgres: `docker compose exec postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql`.

### LSP precision pass (optional)

When `CKG_LSP_ENABLED=true`, after each ingest the worker spawns the
language servers listed in `CKG_LSP_ADAPTERS` (or every adapter whose
binary is on PATH if the list is empty) and upgrades `CALLS` edges with
precise cross-file targets.

Today: **pyright** for Python.

```bash
# Install pyright on the worker (host or in the worker image):
npm install -g pyright
# or:
pip install pyright

# Enable in .env:
CKG_LSP_ENABLED=true
CKG_LSP_ADAPTERS=python      # optional; empty = all available

make restart
```

Trade-off: pyright takes ~30–90 s to cold-index a medium repo. Skip this
flag for size-sensitive workloads; the name-based resolver always runs
and gives you usable (if imprecise) cross-file edges.

### Scaling

- **More ingest throughput**: bump worker `--concurrency` (currently 2) in
  `docker/worker.Dockerfile`, or run more worker containers
  (`docker compose up -d --scale worker=3`).
- **More API throughput**: bump `--workers` in `docker/api.Dockerfile` and
  put a reverse proxy (Caddy/nginx) in front if exposed externally.

### Upgrading

Pull, rebuild, and restart:

```bash
git pull
docker compose pull
docker compose build
make restart
```

Schema migrations on Postgres are applied automatically on API start
(idempotent `Base.metadata.create_all`). Neo4j schema is also applied on
start. For destructive changes we'll add an alembic migration in Phase 2.

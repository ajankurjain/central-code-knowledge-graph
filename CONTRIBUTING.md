# Contributing

Thanks for taking the time. This repo is hours-of-work old and the surface area
is wide — pull requests and issues that close gaps in tests, docs, or language
coverage are especially welcome.

## Scope

`central-code-knowledge-graph` is a multi-repo code knowledge-graph **server**
plus a thin **CLI**. Changes that fit cleanly into one of these are easiest to
land:

- **Parsers** — a new `ckg/parsers/<lang>.py` for a tree-sitter language we
  don't cover yet. Stick to the existing `Parser` protocol; reuse the helpers
  in `ckg/parsers/_generic.py`.
- **LSP adapters** — a new `ckg/lsp/<lang>.py` adapter implementing
  `LspAdapter`. The generic stdio client in `ckg/lsp/client.py` already drives
  the JSON-RPC; you just configure the server command and language id.
- **Source providers** — a new `ckg/sources/<host>.py` provider (e.g. Gitea,
  Codeberg, on-prem GitLab) implementing the `SourceProvider` protocol.
- **Query endpoints** — new REST/GraphQL/MCP queries that read the existing
  graph. Add to all three surfaces for parity.
- **Web UI** — improvements to the Next.js app under `web/`. Token stays in
  `localStorage`; no server-side auth state.

Architecture decisions and known tradeoffs live in `docs/adr/`. Read the
relevant ADR before making structural changes; if you're proposing a shift,
write a new ADR and link it from the PR.

## Dev setup

```bash
git clone https://github.com/ajankurjain/central-code-knowledge-graph.git
cd central-code-knowledge-graph
cp .env.example .env                  # replace every change-me-*
make up                               # docker compose up: Neo4j + Postgres + Redis + API + worker + web + beat

# Python deps for local edits + tests
pip install -e '.[dev]'               # pulls [server] transitively

# (Optional) install the pre-commit credential audit hook
ln -sf ../../scripts/audit-secrets.sh .git/hooks/pre-commit

# Frontend dev
cd web && npm install --legacy-peer-deps && npm run dev
```

Useful Make targets:

| Command | What |
|---|---|
| `make up` / `make down` | Bring the stack up or down |
| `make logs` | Tail all services |
| `make psql` | `psql` inside the Postgres container |
| `make neo4j-shell` | `cypher-shell` inside Neo4j |
| `make test` | Run pytest inside the API container |

## Project structure

See [README.md](README.md#development) for the file tree. Newcomer
shortcut:

| Looking for… | Start at |
|---|---|
| HTTP API | `ckg/api/main.py`, `ckg/api/routes/*` |
| GraphQL schema | `ckg/api/graphql_schema.py` |
| MCP tool catalogue | `ckg/api/routes/mcp.py` |
| Tree-sitter parsers | `ckg/parsers/*.py` |
| Ingest pipeline | `ckg/services/ingest.py` |
| Auto-sync (polling + webhooks) | `ckg/worker/{beat,scheduler}.py`, `ckg/services/webhooks.py` |
| Architecture map / warnings | `ckg/services/architecture.py` |
| CLI | `ckg/cli/main.py` |
| Web UI | `web/app/*` |

## Code style

- **Python**: ruff (`tool.ruff` in `pyproject.toml`). Run `ruff check ckg tests`
  and `ruff check --fix` before pushing.
- **Type hints** on every new public function. `mypy` isn't enforced in CI
  yet but new code should be type-clean.
- **Comments**: write *why*, not *what*. The well-named identifier already
  says what.
- **Imports**: lazy-import heavy or optional deps inside the function that
  needs them, not at module top — particularly in the CLI, which must keep
  cold-start cheap.

## Tests

```bash
pytest -q                             # unit tests (no live backends)
pytest -q tests/integration/          # requires `make up` first
```

- **Unit tests** live next to their domain in `tests/test_*.py`. They never
  spin up Neo4j/Postgres/Redis — those go in `tests/integration/`.
- **Parser tests** auto-skip when the tree-sitter stack is non-functional
  in the host environment (see `tests/conftest.py::pytest_collection_modifyitems`).
- **Don't mock the database** for behaviour we ship — write an integration
  test against the real Compose stack.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) prefixes:

```
feat: add Solidity parser
fix(parsers): handle async function modifiers in Kotlin
docs: explain CKG_LSP_ENABLED in deployment.md
chore: bump tree-sitter-language-pack to 0.7+
test: cover B008 ignore in pyproject
```

Bodies are welcome — explain *why* if the diff doesn't make it obvious.

## Security

The pre-commit hook (`scripts/audit-secrets.sh`) refuses any commit that
contains a credential or an IDE-assistant config file (`.env`, `.claude/`,
`CLAUDE.md`, `.mcp.json`, `.cursor/`, `*.pem`, `*.key`, `id_rsa*`,
`credentials*.json`, etc.). The same script runs as a CI job, so PRs that
ship secrets fail the merge.

Vulnerabilities should be reported privately via the GitHub
[Security Advisory](https://github.com/ajankurjain/central-code-knowledge-graph/security/advisories/new)
flow rather than on the issue tracker.

## Pull requests

1. Branch from `main`. Branch names: `feat/<short>`, `fix/<short>`,
   `docs/<short>`.
2. Keep PRs focused. A parser addition + a refactor of the ingest pipeline
   is two PRs.
3. Update the relevant ADR if you change a documented architectural
   decision.
4. Make sure CI is green before requesting review.
5. Squash on merge unless the history is genuinely useful — most isn't.

## Releases

Maintainers only. See [RELEASING.md](RELEASING.md). PyPI publishes are
gated on the `pypi` GitHub environment (required reviewer + `v*` tag-only
deployment policy), so a stray tag cannot ship a release.

## Filing issues

- **Bugs**: include the failing command, the version (`ckg --version` or
  `pip show central-code-knowledge-graph`), and the relevant log snippet.
  Logs are JSON-structured; `docker compose logs api | jq` is helpful.
- **Feature requests**: open an issue describing the use case, not the
  implementation. We'll discuss the design before coding.
- **Discussion / open-ended**: GitHub Discussions if it doesn't fit a
  specific issue.

## License

By contributing you agree your work is licensed under the project's
[MIT license](LICENSE).

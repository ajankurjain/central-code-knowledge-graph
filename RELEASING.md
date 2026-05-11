# Releasing

PyPI publish is fully automated via GitHub Actions + Trusted Publishing
(OIDC). No long-lived secrets in the repo.

## One-time PyPI setup

Do this once per project (only the repo owner needs to do it).

1. Sign in at <https://pypi.org/manage/account/>. Enable 2FA if not already.
2. Visit <https://pypi.org/manage/account/publishing/> and click
   **"Add a new pending publisher"**.
3. Fill the form:
   - **PyPI Project Name**: `central-code-knowledge-graph`
   - **Owner**: `ajankurjain`
   - **Repository name**: `central-code-knowledge-graph`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
4. Save. The pending publisher is now waiting; it'll be promoted to a real
   publisher on the first successful publish.

## One-time GitHub setup

In the GitHub repo:

1. **Settings → Environments → New environment** → name it `pypi`.
2. Add a **required reviewer** (yourself) to that environment. This adds a
   manual approval step before each publish, so a stray tag push can't ship.

That's it. From here every release is a tag.

## Cutting a release

```bash
# 1. Decide the new version.
#    Bump pyproject.toml -> [project] version
vim pyproject.toml

# 2. Commit + tag.
git add pyproject.toml
git commit -m "release: v0.1.0"
git tag v0.1.0
git push
git push --tags

# 3. Watch the workflow.
#    https://github.com/ajankurjain/central-code-knowledge-graph/actions
#    - `build` job runs first (sdist + wheel + tag↔version sanity check)
#    - `publish` job is gated on the `pypi` environment; approve it from the
#      Actions UI to upload to PyPI.

# 4. Verify the release.
pip install --upgrade central-code-knowledge-graph
ckg --help
```

## Version policy

We follow [SemVer](https://semver.org/):

- `0.x.y` — pre-1.0, anything can change between minors.
- `1.x.y` — public API stable (REST, GraphQL, MCP, CLI shape).

Each release is a single immutable PyPI artefact. If something goes wrong:

- Yank the bad release on PyPI (it stays uninstallable by name; existing
  installs are unaffected).
- Bump the patch number and tag again.

## What gets shipped

- `pip install central-code-knowledge-graph` — **CLI only** (light: `typer`,
  `httpx`, `rich`). Talks to a Docker-deployed server over REST.
- `pip install central-code-knowledge-graph[server]` — adds FastAPI/Celery/
  Neo4j-driver/tree-sitter/sentence-transformers/etc. for running the
  server outside Docker.
- `pip install central-code-knowledge-graph[dev]` — adds pytest/ruff and
  pulls `[server]` so the parser tests can run.

The Docker images (`docker compose build`) are independent of PyPI and
always include everything; bumping the PyPI version doesn't automatically
re-tag Docker images.

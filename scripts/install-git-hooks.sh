#!/usr/bin/env bash
# Install repo-local git hooks. Run from the repo root via `make install-hooks`.
#
# We install a pre-push hook (not pre-commit) on purpose:
#   * pre-commit fires on every WIP commit and slows the iteration loop
#   * pre-push fires once before the network round-trip — the same place
#     CI would catch you anyway — and only adds friction when something
#     would actually break the build
#
# The hook short-circuits when pushing branches the user is fixing AFTER
# noticing CI broke (set SKIP_CKG_PREPUSH=1 to bypass for one push).

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .git ]; then
    echo "✗ run this from a git checkout (no .git/ here)"
    exit 1
fi

mkdir -p .git/hooks

cat > .git/hooks/pre-push <<'HOOK'
#!/usr/bin/env bash
# Block pushes whose code wouldn't survive CI.
#
# This is the exact gate `.github/workflows/ci.yml` runs. If you've just
# noticed CI is red and want to push a one-off fix without re-running the
# full check, prefix the push:  SKIP_CKG_PREPUSH=1 git push
set -euo pipefail

if [ "${SKIP_CKG_PREPUSH:-0}" = "1" ]; then
    echo "ckg pre-push: SKIPPED (SKIP_CKG_PREPUSH=1)"
    exit 0
fi

# Resolve the repo root regardless of where `git push` was invoked from.
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# Only block when there are Python or test changes — README-only / web-only
# pushes don't need the lint pass.
RANGE_TO_CHECK="@{push}..HEAD"
# Fall back if no upstream is set yet (first push of a new branch).
if ! git rev-parse --verify --quiet "$RANGE_TO_CHECK" >/dev/null; then
    RANGE_TO_CHECK="origin/HEAD..HEAD"
    if ! git rev-parse --verify --quiet "$RANGE_TO_CHECK" >/dev/null; then
        RANGE_TO_CHECK="HEAD~1..HEAD"
    fi
fi
CHANGED="$(git diff --name-only "$RANGE_TO_CHECK" 2>/dev/null || echo "")"
if [ -z "$CHANGED" ] || ! echo "$CHANGED" | grep -qE '\.py$|^tests/|^ckg/|^pyproject\.toml$|^\.github/workflows/'; then
    echo "ckg pre-push: no Python / CI changes — skipping ruff + pytest"
    exit 0
fi

# Run the same check CI runs. Bail with a clear pointer if the api
# container isn't available — operator can fall through with SKIP=1.
if ! docker compose ps api >/dev/null 2>&1 || ! docker compose ps api | grep -q "Up "; then
    cat >&2 <<MSG
ckg pre-push: api container not running — can't run lint locally.

Options:
  1.  make up           # start the stack, then retry the push
  2.  SKIP_CKG_PREPUSH=1 git push <args>   # bypass for this push
MSG
    exit 1
fi

echo "ckg pre-push: running 'make check' (ruff + pytest)…"
if ! make check; then
    cat >&2 <<MSG

ckg pre-push: BLOCKED — lint or tests failed. Fix the issues above, or:
  SKIP_CKG_PREPUSH=1 git push <args>
to push anyway (e.g. README-only fixes during the same window).
MSG
    exit 1
fi
echo "ckg pre-push: ✓ ready to push"
HOOK

chmod +x .git/hooks/pre-push
echo "✓ installed .git/hooks/pre-push"
echo "  it runs 'make check' on every push, but only when Python files changed."
echo "  bypass for one push with:  SKIP_CKG_PREPUSH=1 git push <args>"

#!/usr/bin/env bash
# Pre-commit / pre-push audit: refuse to ship credentials or Claude/IDE
# assistant configs.
#
# Run manually:   ./scripts/audit-secrets.sh
# Or install as a git hook:
#   ln -sf ../../scripts/audit-secrets.sh .git/hooks/pre-commit
#
# Exits non-zero if anything suspicious is staged or already tracked.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yel()   { printf '\033[0;33m%s\033[0m\n' "$*"; }

fail=0

# 1. Files that should NEVER be tracked, no matter what.
banned_paths=(
  '^\.env$'
  '(^|/)\.env\.[^/]+$'
  '(^|/)\.claude/'
  '(^|/)CLAUDE\.md$'
  '(^|/)CLAUDE\.local\.md$'
  '(^|/)\.claude\.json$'
  '(^|/)\.claude\.local\.json$'
  '(^|/)claude_desktop_config\.json$'
  '(^|/)settings\.local\.json$'
  '(^|/)\.mcp\.json$'
  '(^|/)\.cursor/'
  '(^|/)\.cursorrules$'
  '(^|/)\.continue/'
  '(^|/)\.aider'
  '(^|/)\.windsurf/'
  '(^|/)credentials\.json$'
  '(^|/)id_rsa$'
  '(^|/)id_ed25519$'
  '(^|/).*\.pem$'
  '(^|/).*\.key$'
  '(^|/).*\.pfx$'
  '(^|/).*\.p12$'
)

# Allowed paths even if they match (docs ABOUT Claude/Cursor, not configs FOR them).
# Match anchored against full path.
allowed_paths=(
  '^\.env\.example$'
  '^integrations/(cursor|vscode|claude-code)/README\.md$'
  '^README\.md$'
  '^docs/'
  '^scripts/audit-secrets\.sh$'
)

is_allowed() {
  local f="$1" allowpat
  for allowpat in "${allowed_paths[@]}"; do
    if printf '%s' "$f" | grep -Eq "$allowpat"; then return 0; fi
  done
  return 1
}

tracked="$(git ls-files)"
staged="$(git diff --cached --name-only --diff-filter=ACMR)"

for ban in "${banned_paths[@]}"; do
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if is_allowed "$f"; then continue; fi
    red "  banned (tracked or staged): $f  matches  $ban"
    fail=1
  done < <(printf '%s\n%s\n' "$tracked" "$staged" | sort -u | grep -E "$ban" || true)
done

# 2. Secret-pattern grep across staged content + already-tracked files.
secret_patterns=(
  '\bgh[pousr]_[A-Za-z0-9]{20,}'                  # GitHub PAT
  '\bsk-[A-Za-z0-9]{20,}'                         # OpenAI / many vendors
  '\bxox[baprs]-[A-Za-z0-9-]{10,}'                # Slack
  '\bAKIA[0-9A-Z]{16}\b'                          # AWS access key id
  '\baws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{30,}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  '\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}'   # JWT
)

scan_targets="$(printf '%s\n%s\n' "$tracked" "$staged" | sort -u)"
if [ -n "$scan_targets" ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    [ ! -f "$f" ] && continue
    for sec in "${secret_patterns[@]}"; do
      # Strip lines that are deliberate placeholders / docs before evaluating
      if grep -InE "$sec" "$f" 2>/dev/null | grep -vE 'REPLACE_WITH|change-me|example|placeholder' >/dev/null; then
        red "  secret-pattern hit in: $f  ($sec)"
        grep -InE "$sec" "$f" | head -3 | sed 's/^/      /'
        fail=1
      fi
    done
  done <<< "$scan_targets"
fi

# 3. .git/config must not have a token embedded in the remote URL.
if grep -qE 'gh[pousr]_[A-Za-z0-9]{20,}|:[^/]+@github\.com' .git/config 2>/dev/null; then
  red "  token embedded in .git/config remote URL"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  red ""
  red "Audit FAILED — see hits above. Remove the file or pattern before committing."
  red "If a finding is a deliberate documentation example, add it to the 'allowed_paths' allowlist in this script."
  exit 1
fi

green "Audit OK — no credentials, Claude/IDE configs, or embedded tokens found."

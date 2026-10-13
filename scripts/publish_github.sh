#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
remote='https://github.com/Krishal743/used-car-search-tool.git'
dry_run=false
if [ "${1:-}" = '--dry-run' ]; then
  dry_run=true
elif [ "$#" -ne 0 ]; then
  echo 'Usage: ./scripts/publish_github.sh [--dry-run]' >&2
  exit 2
fi

if grep -Eq '^GEMINI_API_KEY=.+$' "$root/.env.example"; then
  echo 'Refusing to publish: .env.example contains a Gemini API key.' >&2
  exit 1
fi

if [ "$dry_run" = false ]; then
  if ! account=$(gh api user --jq .login 2>/dev/null); then
    echo 'Cannot authenticate with GitHub. Check connectivity, then run: gh auth login -h github.com' >&2
    echo 'After login, run: gh auth setup-git' >&2
    exit 1
  fi
  if [ "$account" != 'Krishal743' ]; then
    echo "GitHub CLI is authenticated as $account; this push targets Krishal743." >&2
    exit 1
  fi
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if [ "$dry_run" = true ]; then
  git init --quiet -b main "$tmp/repo"
else
  git clone --quiet "$remote" "$tmp/repo"
fi

tar -C "$root" \
  --exclude='*/__pycache__' --exclude='*.pyc' --exclude='*/.pytest_cache' \
  -cf - .gitignore .env.example README.md backend docs \
  frontend/index.html frontend/package.json frontend/src frontend/vite.config.js \
  scripts | tar -C "$tmp/repo" -xf -

git -C "$tmp/repo" add -A
token_prefix='github_'
token_prefix+='pat_'
if git -C "$tmp/repo" grep --cached -q -I -E "(AIza[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|${token_prefix}|AQ\.[A-Za-z0-9_-]{20,})"; then
  echo 'Refusing to publish: a staged file contains a key-like value.' >&2
  exit 1
fi

echo 'Files staged for GitHub:'
git -C "$tmp/repo" diff --cached --name-only
if git -C "$tmp/repo" diff --cached --quiet; then
  echo 'No changes to publish.'
  exit 0
fi

git -C "$tmp/repo" -c user.name="${GIT_AUTHOR_NAME:-Krishal743}" \
  -c user.email="${GIT_AUTHOR_EMAIL:-Krishal743@users.noreply.github.com}" \
  -c commit.gpgsign=false commit --quiet -m 'Add Motorwise MVP and project documentation'

if [ "$dry_run" = true ]; then
  echo 'Dry run passed. No GitHub push was attempted.'
else
  git -C "$tmp/repo" push -u origin HEAD
  echo "Published commit $(git -C "$tmp/repo" rev-parse --short HEAD) to $remote"
fi

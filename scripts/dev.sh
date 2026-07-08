#!/usr/bin/env bash
# Stand up the basic dev environment for housekeeping.
# One command a newcomer runs after cloning: sync deps and wire up the hooks.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> syncing the uv environment (deps + dev tooling)"
uv sync

echo "==> enabling the committed git hooks (pre-commit + commit-msg)"
git config core.hooksPath .githooks

cat <<'EOF'

Dev environment ready.

  uv run pytest             # tests
  uv run ruff check .       # lint
  uv run housekeeper check  # audit this repo

Hooks are active: commits now run the full CI gate locally
(git commit --no-verify to skip for one commit).
EOF

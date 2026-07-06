# .githooks

Committed git hooks that run this repo's full CI gate locally, before a commit
lands — so failures surface here instead of after a push.

## Activate

Hooks are not enabled automatically on clone. Run once per checkout:

```sh
git config core.hooksPath .githooks
```

## What runs

`pre-commit` mirrors CI:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/housekeeper`
- `uv run pytest`
- `run-straitjacket` — see below

`commit-msg` enforces Conventional Commits on the subject line, matching the
`conventional` PR-title check.

## run-straitjacket

Runs straitjacket at the exact version this repo pins in CI, read from
`.github/workflows/straitjacket.yml`. The released binary is cached per version
under `$XDG_CACHE_HOME/straitjacket/<version>/`, so the download happens once.
This keeps local results identical to CI regardless of any globally installed
straitjacket. Bump the workflow pin and the hook follows.

## Bypass

`git commit --no-verify` skips the hooks for a single commit.

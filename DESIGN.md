# Housekeeping — Design

Housekeeping checks that a GitHub repo is in good order. It's for someone who
maintains a pile of public and private repos and keeps hitting the same
problems: no branch protection, stale lockfiles, missing CI, READMEs that
rotted, dead website links. You point it at one repo, it tells you what's out
of order, and it helps you fix it. It's a setup/audit tool you run when you
touch a repo — not a daemon, not a nightly nag.

## Philosophy

Same split as Straitjacket: **deterministic checks do the work, judgment lives
at the edges.** Every check is plain code — no model in the loop. The things
that genuinely need taste (is this README actually *good*?) are Claude Code
skills layered on top, and they consume the deterministic report rather than
re-deriving it.

Second principle: **check ≠ fix.** Checking is always safe and read-only.
Fixing is a separate, explicit invocation. Every fix explains what it's about
to do and seeks confirmation before touching anything. For fixes that need
commits, the operator can approve going all the way: branch → commit → push →
open a PR. Nothing mutates without an explicit yes.

## Architecture

One Python project, managed with uv. No shell scripts.

```
housekeeping/
  pyproject.toml            # uv-managed; entry point `housekeeper`
  src/housekeeper/
    cli.py                  # check / fix / report
    context.py              # RepoContext: gh wrapper, clone cache, ecosystem detection
    registry.py             # @check registry, Result type
    checks/
      branch_protection.py
      ci.py                 # ci-exists + ci-green
      dependabot.py
      lockfiles.py
      straitjacket.py
      readme.py
      website.py
      license.py
      repo_meta.py
      stale.py
  skills/
    housekeeping/SKILL.md   # /housekeeping — run audit, interpret, drive fixes
    tidy-up/SKILL.md        # audit front door + README judgment pass
  housekeeping.toml         # defaults: severities, overrides
  README.md
```

Runtime dependencies stay minimal: stdlib (`argparse`, `tomllib`, `json`,
`subprocess`) plus at most one or two conveniences (`rich` for the report
table). GitHub access goes through the `gh` CLI via subprocess — it already
holds auth, handles pagination, and means housekeeping never manages tokens.
Clones go through `git`. Install with `uv tool install .`, or run in-tree
with `uv run housekeeper`.

### Check contract

A check is a module in `checks/` that registers itself:

```python
@check("lockfiles", needs=["clone"], fixable=True)
def lockfiles(ctx: RepoContext) -> Result: ...
```

- **`RepoContext`** gives it everything: `ctx.repo` (owner/name),
  `ctx.workdir` (checkout path, populated only when `needs=["clone"]`),
  `ctx.api(path)` (gh api wrapper), `ctx.ecosystems` (shared detection),
  `ctx.visibility`, `ctx.config` (merged toml).
- **`Result`** carries `status` (`PASS | FAIL | SKIP`), `details`, and an
  optional `note` — skips are first-class and always say *why* ("no homepage
  set and none expected", "branch protection unavailable on this plan").
- A fixable check also provides a `fix(ctx)` in the same module, so the check
  and its remedy never drift apart.

### Two data sources

- **API-side checks** call `ctx.api()` only — branch protection, repo
  metadata, workflow runs, Dependabot alert settings. Fast, no disk.
- **File-side checks** get a checkout. Run inside an existing clone and
  housekeeping uses your working tree; run against a repo you don't have
  locally and it shallow-clones into `~/.cache/housekeeping/<owner>/<repo>`.

### CLI

One repo at a time:

```sh
housekeeper check                    # repo inferred from cwd's git remote
housekeeper check zmaril/entl        # or named explicitly
housekeeper check --only lockfiles,branch-protection
housekeeper fix dependabot           # explain, confirm, then act
housekeeper report                   # re-render the last check run
```

`check` prints a human table and writes JSON results to
`~/.cache/housekeeping/results/<owner>-<repo>.json` so `report` and the
skills can consume them without re-running. Exit code is nonzero if any
non-skipped check failed.

### Fix flow

`housekeeper fix <check>` for each failing check:

1. Show what's wrong and exactly what the fix will do (settings diff, file
   diff, or PR plan).
2. Ask for confirmation. No is always safe.
3. Apply. API-side fixes (rulesets, repo settings) apply directly on yes.
   File-side fixes write to a branch; if the operator says they want it
   committed and pushed, housekeeping commits, pushes the branch, and opens
   a PR via `gh pr create`. It never pushes to the default branch.

## Check catalog (v1)

| Check | Source | Pass criteria | Fix |
|---|---|---|---|
| `branch-protection` | API | Default branch has a ruleset (or classic protection): PRs required, status checks required, force-push and deletion blocked | Apply a standard ruleset via API |
| `ci-exists` | clone | `.github/workflows/` has a workflow triggered on PR + push-to-main whose jobs cover **test** and **lint** for each detected ecosystem | Scaffold a workflow from per-ecosystem templates |
| `ci-green` | API | Latest completed default-branch run of **every** repo workflow (GitHub's `dynamic/` internals excluded) concluded `success` | none — report only |
| `dependabot` | clone + API | `.github/dependabot.yml` exists and covers every detected ecosystem (cargo, bun/npm, pip/uv, actions, …); vulnerability alerts + security updates enabled | Generate/extend the yml; enable settings via API |
| `secret-scanning` | API | Secret scanning + push protection enabled (skip-with-note on private repos without Advanced Security) | Enable via API |
| `workflow-permissions` | API | Default workflow `GITHUB_TOKEN` is read-only and cannot approve PRs | Set via API |
| `lockfiles` | clone | For each manifest, the lockfile is committed and **in sync**: `cargo metadata --locked`, `bun install --frozen-lockfile --dry-run`, `uv lock --check`, `npm ci --dry-run` per ecosystem | Regenerate lockfile on a branch |
| `gitignore` | clone | `.gitignore` exists and covers each ecosystem's build junk (`target/`, `node_modules/`, `.venv/`, …) | Append missing patterns |
| `straitjacket` | clone | A CI workflow step runs straitjacket — wiring only, findings are straitjacket's own business | Add the CI step from template |
| `readme` | clone | Deterministic floor: README exists, has a title + description, install and usage sections, ≥ ~150 words, no broken relative links, mentions license | Escalates to the `tidy-up` skill's README quality pass |
| `website` | API + HTTP | Repo homepage URL is set and returns 200 (following ≤3 redirects, 10s timeout); README badge/doc links resolve | none — report only |
| `license` | clone + API | LICENSE file present and GitHub detects a license | Drop in MIT with current year |
| `repo-meta` | API | Description set; ≥1 topic; issues enabled | Prompt for values, set via API |
| `stale` | API | No PRs idle >30 days; no merged-but-undeleted branches | none — report only |

Ecosystem detection lives once in `context.py` (look for `Cargo.toml`,
`package.json` + which lockfile, `pyproject.toml`, `go.mod`,
`.github/workflows`) and is shared by `ci-exists`, `dependabot`, and
`lockfiles` so they never disagree about what the repo is.

### Severities and per-repo config

Global `housekeeping.toml` sets the default severity of each check
(`required` | `recommended` | `off`). A repo can carry `.housekeeping.toml`
at its root to override — skip `website` on a library, declare the expected
homepage URL explicitly, mark a sandbox exempt from `branch-protection`.

Private repos get a softer default profile: `website` and `license` drop to
`recommended`, and since full branch protection on private repos needs a paid
plan, that check reports skip-with-note ("unavailable on this plan") rather
than failing.

## Skills layer

One skill, **`tidy-up`** (installed via plugin as `/housekeeping:tidy-up`, or
via skills.sh into any agent): runs `housekeeper check` on the current repo,
reads the JSON results, explains failures in plain language, and offers to
drive fixes one at a time — the interactive front door; the Python is the
engine. It also carries the README judgment pass the deterministic `readme`
check can't do: read it as a newcomer (what is this, why would I want it, how
do I start — in 30 seconds?) and draft concrete edits rather than a critique.
Originally these were two skills, but they're one workflow with two phases.

## Out of scope (v1)

- Multi-repo sweeps (`--all`) and any scheduling. This is a run-it-when-you-
  touch-a-repo tool. The single-repo results format is designed so a sweep
  is a loop, not a redesign, if it's ever wanted.
- Auto-merge, or any mutation without per-fix confirmation.
- A GitHub Action distributed into each repo.
- Org-level checks, other people's repos, GitHub Enterprise.
- Issue/PR template enforcement, CODEOWNERS, contributing guides — easy to
  add later as new modules in `checks/`, which is the point of the registry.

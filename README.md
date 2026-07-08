# housekeeping

[![Powderworks Housekeeping on the GitHub Marketplace](https://img.shields.io/badge/marketplace-powderworks--housekeeping-blue?logo=github)](https://github.com/marketplace/actions/powderworks-housekeeping)

Checks that a GitHub repo is in good order — branch protection, CI with tests
and lint, no CI step masking its own failure with `continue-on-error`, a
scheduled run so bitrot surfaces on its own, bounded job timeouts, no
rerun-until-green test retries, a pinned (non-floating) CI toolchain, dependabot
coverage, secret scanning, read-only workflow tokens, lockfiles committed and in
sync, gitignore coverage, CODEOWNERS routing review, shell scripts corralled
under `scripts/` with a `dev.sh` that stands up the dev environment,
TODO/FIXME markers kept in the todo file rather than scattered,
[straitjacket](https://github.com/zmaril/Straitjacket) wired into CI, stylelint
on stylesheets, vale on prose style and codespell on typos, a README that clears
the floor, a reachable website, a license, sane repo metadata, and no stale PRs
or branches. One repo at a time; run it when you touch a repo.

Checking is always read-only. Fixing is separate, explains itself, and asks
before changing anything; file fixes land on a `housekeeping/<check>` branch
and only push + open a PR on an explicit yes.

The defaults are my interpretation of what good code looks like, whether
it's public or private — snobby yet configurable, in the family spirit of
[straitjacket](https://github.com/zmaril/Straitjacket). Public repos get the
full audience-facing treatment; private repos soften those checks (website,
license, changelog, README polish, metadata), because a repo with no audience
doesn't owe anyone a changelog. Engineering hygiene — CI, lockfiles,
dependabot, secret scanning — is required either way. `.housekeeping.toml`
overrides any of it per repo.

## Install

```sh
uv tool install git+https://github.com/zmaril/housekeeping
# or from a checkout:
uv tool install .
```

Needs `gh` (authenticated) and `git`. Lockfile sync checks use whichever of
`cargo`/`bun`/`npm`/`uv`/… are installed and degrade to presence-only otherwise.

### GitHub Action

Run the audit in your own repo's CI — on PRs, pushes, and a weekly cron for
the things that rot without commits (dead links, stale PRs, settings drift):

```yaml
name: housekeeping
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 7 * * 1"

jobs:
  housekeeping:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: zmaril/housekeeping@v0.9.0   # pin the full version — newest is on the Releases page
```

**Pin the full version, not a moving major tag.** Housekeeping adds checks in
minor releases; a floating `@v0` would apply every new check to your repo the
moment it ships, turning an unrelated PR red with something you never opted
into. Pin the exact release (or a commit SHA) so new checks arrive only when you
deliberately bump — on a PR that's *about* that upgrade, where you can read the
[changelog](CHANGELOG.md) and decide. Dependabot/Renovate can raise those bumps
for you. The newest release is on the
[Releases page](https://github.com/zmaril/housekeeping/releases). Results land in
the job summary; a required-check failure fails the run.
The default workflow token can't read some admin-level settings
(vulnerability alerts, secret scanning, workflow permissions) — those checks
skip with a note rather than guessing; pass `with: token:` a fine-grained
PAT with read-only Administration scope for full coverage. Tune or disable
checks with `.housekeeping.toml` in your repo root.

### Fleet captain

Repos audit themselves; the captain checks the auditors. A captain repo
carries a `housecaptain.toml` naming the fleet:

```toml
name = "powderworks"

[[member]]
repo = "zmaril/housekeeping"

[[member]]
repo = "zmaril/entl"
note = "pre-release, in flux"

[policy.checks]
conventional-commits = "required"

[policy]
locked = ["checks.stray-files", "stray-files.allow"]
```

Policy is expectation (divergence surfaced as a conflict) unless **locked**:
members declare `fleet = "owner/repo"` in their `.housekeeping.toml`, their
own audits fetch the manifest and enforce locked keys as law — a PR that
sets a locked key fails its own CI, so nobody excepts themselves in the same
diff that adds the mess. Locking requires a top-level `captain = "owner/repo"`
in the manifest; the captain flags members that don't declare their fleet.

**Adoption note:** the PR that introduces locks to the manifest will have a
red captain check, by construction. The captain reads member configs from
their main branches — so members that haven't merged their `fleet = ...`
lines yet show as conflicts, and the captain repo itself conflicts on the
very PR that adds its own declaration (it can't bless its own enrollment).
Merge order: member fleet-lines first, then the manifest PR — merged red on
that one self-referential conflict — and the push-triggered captain run
right after merge is the real verdict.

`housekeeper captain` (or the action with `captain: housecaptain.toml`) is
the API-only delegation check: each member has a housekeeping workflow, it
fires on pull_request + push + schedule, its latest default-branch run is
green, and the member's `.housekeeping.toml` doesn't contradict fleet
policy — divergence is surfaced as a conflict for a human to reconcile,
never silently resolved. `housekeeper fleet` is the deep version: the full
audit against every member from your machine (members audited concurrently),
with a scoreboard. `--html FILE` writes a standalone dashboard — the check
matrix plus a table of every open PR and issue across the fleet. And
`housekeeper captain --dispatch` (action input `dispatch: true`) is the
fleet's "now" button: it triggers every member's self-audit immediately, so
a new check reaches everyone without waiting out the weekly crons.

`housekeeper serve housecaptain.toml` puts the same dashboard behind a local
web server with a **Regenerate** button (and an optional 60s auto-refresh)
that re-audits the fleet on demand — no re-running the command by hand.

#### Managed configs

Some checks pass on presence but the config's *content* is a fleet decision —
everyone should lint CSS by the same rules and spell-check against the same
vocabulary. The captain can own the canonical file and push it outward.
Canonical configs live under `.fleet/` in the captain repo, declared in the
manifest:

```toml
[[policy.managed-config]]
check = "stylelint"
paths = { ".stylelintrc.json" = ".fleet/stylelintrc.json" }

[[policy.managed-config]]
check = "vale"                     # trailing-slash keys are directory syncs
paths = { ".vale.ini" = ".fleet/vale/.vale.ini", "styles/" = ".fleet/vale/styles/" }
```

`housekeeper captain --sync-configs` (action input `sync-configs: true`) opens
an isolated, config-only PR on each member whose copy has drifted — branch
`housekeeping/fleet-config-<check>`, reused idempotently, titled `chore(config):
sync <check> config from fleet`. This is distribution, not a fix: the captain
ships the artifact for the member to adopt at their own pace and **never**
touches member code or tries to make the resulting lint pass — that stays the
member's own, one-repo job. Drift shows on the captain report as a note, never
as a member-CI failure. It needs a token with `contents:write` +
`pull_requests:write` on the members.

Wire it to fan out on merge with a workflow in the captain repo:

```yaml
name: fleet-sync
on:
  push:
    branches: [main]
    paths: ['.fleet/**']          # only when a canonical config changes
  schedule:
    - cron: "0 7 * * 1"           # backstop: new members, PRs closed unmerged
  workflow_dispatch:
concurrency: { group: fleet-sync }
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: zmaril/housekeeping@v0.9.0   # pin the full version
        with:
          captain: housecaptain.toml
          sync-configs: true
          token: ${{ secrets.FLEET_PAT }}
```

### Agent skill

The `tidy-up` skill audits the repo you're in, drives fixes, and does a
README quality pass. Install it into Claude Code as a plugin:

```
/plugin marketplace add zmaril/housekeeping
/plugin install housekeeping@powderworks
```

then invoke `/housekeeping:tidy-up`. Or install it into any agent
(Claude Code, Cursor, Copilot, …) via [skills.sh](https://www.skills.sh/):

```sh
npx skills add zmaril/housekeeping
```

Either way, the skill offers to install the `housekeeper` CLI if it's missing.

## Usage

```sh
housekeeper check                  # repo inferred from cwd's git remote
housekeeper check zmaril/entl      # or named explicitly
housekeeper check --only lockfiles,branch-protection
housekeeper fix dependabot         # explain, confirm, then act
housekeeper report                 # re-render the last run
```

`check` exits nonzero if any required check fails, so it can gate other
automation. Results are saved as JSON under `~/.cache/housekeeping/results/`.

## Per-repo config

Drop `.housekeeping.toml` in a repo root to override defaults:

```toml
[checks]
website = "off"                    # required | recommended | off

[website]
url = "https://straitjacket.dev"   # expected homepage

[[codegen]]                        # committed generated code: CI must regen + zero-diff
name = "ruby bindings"
command = "make bindgen"
```

Private repos automatically soften `website` and `license` to recommended,
and branch protection reports skip-with-note where the plan doesn't allow it.

## Skills

`skills/tidy-up/` is the skill source — front door for the audit, fix
driving, and the README judgment pass the deterministic check can't do.
Working on housekeeping itself? Symlink it into `~/.claude/skills/` instead
of installing the plugin.

## Design

See [notes/design.md](notes/design.md).

## Contributing

Issues and PRs welcome. The most useful thing you can send is a repo where
housekeeper judges wrongly — a check that passes when it shouldn't, fails
when it shouldn't, or a skip that deserves a better note. Concrete examples
beat descriptions.

Clone, then run `./scripts/dev.sh` — it syncs the uv environment and wires up
the committed git hooks, so you're ready to test, lint, and audit in one step.

New checks are one module in `src/housekeeper/checks/` — see the check
contract in [notes/design.md](notes/design.md). House rules: checks are read-only, fixes
explain themselves and confirm before touching anything, and skips say why.
PR titles follow [conventional commits](https://www.conventionalcommits.org)
(`type(scope): summary`) — CI enforces it, and squash merges inherit the
title, so main's history stays machine-readable.
`uv run pytest` and `uv run ruff check .` before pushing; CI also runs
[straitjacket](https://github.com/zmaril/Straitjacket) on everything,
prose included.

## License

[MIT](LICENSE).

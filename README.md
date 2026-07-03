# housekeeping

Checks that a GitHub repo is in good order — branch protection, CI with tests
and lint, dependabot coverage, secret scanning, read-only workflow tokens,
lockfiles committed and in sync, gitignore coverage,
[straitjacket](https://github.com/zmaril/Straitjacket) wired into CI, a README
that clears the floor, a reachable website, a license, sane repo metadata, and
no stale PRs or branches. One repo at a time; run it when you touch a repo.

Checking is always read-only. Fixing is separate, explains itself, and asks
before changing anything; file fixes land on a `housekeeping/<check>` branch
and only push + open a PR on an explicit yes.

## Install

```sh
uv tool install git+https://github.com/zmaril/housekeeping
# or from a checkout:
uv tool install .
```

Needs `gh` (authenticated) and `git`. Lockfile sync checks use whichever of
`cargo`/`bun`/`npm`/`uv`/… are installed and degrade to presence-only otherwise.

### Claude Code plugin

The two skills ship as a plugin:

```
/plugin marketplace add zmaril/housekeeping
/plugin install housekeeping@housekeeping
```

Then `/housekeeping:housekeeping` audits the repo you're in and drives fixes,
and `/housekeeping:readme-review` does the README quality pass. The skills
will offer to install the `housekeeper` CLI if it's missing.

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
```

Private repos automatically soften `website` and `license` to recommended,
and branch protection reports skip-with-note where the plan doesn't allow it.

## Skills

`skills/` holds two Claude Code skills: `housekeeping` (front door — runs the
audit, explains, drives fixes) and `readme-review` (the judgment pass the
deterministic README check can't do). Symlink them into `~/.claude/skills/`
to use them everywhere.

## Design

See [DESIGN.md](DESIGN.md).

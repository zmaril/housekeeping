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

### Agent skill

The `tidy-up` skill audits the repo you're in, drives fixes, and does a
README quality pass. Install it into Claude Code as a plugin:

```
/plugin marketplace add zmaril/housekeeping
/plugin install housekeeping@housekeeping
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
```

Private repos automatically soften `website` and `license` to recommended,
and branch protection reports skip-with-note where the plan doesn't allow it.

## Skills

`skills/tidy-up/` is the skill source — front door for the audit, fix
driving, and the README judgment pass the deterministic check can't do.
Working on housekeeping itself? Symlink it into `~/.claude/skills/` instead
of installing the plugin.

## Design

See [DESIGN.md](DESIGN.md).

## Contributing

Issues and PRs welcome. The most useful thing you can send is a repo where
housekeeper judges wrongly — a check that passes when it shouldn't, fails
when it shouldn't, or a skip that deserves a better note. Concrete examples
beat descriptions.

New checks are one module in `src/housekeeper/checks/` — see the check
contract in [DESIGN.md](DESIGN.md). House rules: checks are read-only, fixes
explain themselves and confirm before touching anything, and skips say why.
`uv run pytest` and `uv run ruff check .` before pushing; CI also runs
[straitjacket](https://github.com/zmaril/Straitjacket) on everything,
prose included.

## License

[MIT](LICENSE).

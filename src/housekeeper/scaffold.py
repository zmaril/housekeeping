"""Scaffold a new fleet-compliant repository skeleton.

`housekeeper new <name>` writes the files a fresh powderworks-fleet member
carries: the self-audit workflow, straitjacket + conventional-commit CI, git
hooks, CODEOWNERS, dependabot, a per-flavor CI job and manifest, and the
audience-facing floor (README, LICENSE, CHANGELOG, design notes). The templates
mirror what the compliant repos in the fleet actually ship — where a check
module already owns the canonical text (the MIT license, the conventional-commit
workflow, a language's CI job), the scaffold reuses that text instead of a
second copy drifting out of sync.

What the scaffold deliberately does NOT do is fake state a human has to create:
there's no lockfile (it comes from running dev.sh), no repo settings (branch
protection, secret scanning), and no fleet-managed lint configs (stylelint,
vale, codespell, biome — those arrive from the captain via
`housekeeper captain --sync-configs`). Those land in the printed "next steps".
"""

from __future__ import annotations

import datetime
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .checks.conventional_commits import WORKFLOW as CONVENTIONAL_WORKFLOW
from .checks.dependabot_automerge import WORKFLOW as DEPENDABOT_AUTOMERGE_WORKFLOW
from .checks.license import MIT
from .languages import BUN_TYPECHECK, ECOSYSTEMS

# ---- Fleet-wide constants ----------------------------------------------------

OWNER = "zmaril"
OWNER_NAME = "Zack Maril"
FLEET = "zmaril/powderworks"
# Pin the FULL versions the way the fleet checklist calls for — a floating major
# would let a new housekeeping/straitjacket release change CI without a bump.
HOUSEKEEPING_ACTION = "zmaril/housekeeping@v0.19.0"
STRAITJACKET_ACTION = "zmaril/straitjacket@v0.2.3"
STRAITJACKET_VERSION = "v0.2.3"

# The flavor a caller picks, mapped to its ecosystem key in languages.py. The
# ecosystem carries the CI job template, gitignore build-junk, dependabot id.
FLAVORS = {"rust": "cargo", "bun": "bun", "python": "uv"}


# ---- Result ------------------------------------------------------------------


@dataclass
class ScaffoldResult:
    """What a scaffold run produced: the destination, and the repo-relative paths
    written versus skipped (already present, no --force). `next_steps` are the
    things a scaffold honestly can't do — they need GitHub, deps, or the captain."""

    dest: Path
    flavor: str
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


# ---- Workflow assembly -------------------------------------------------------


def _with_timeout(text: str) -> str:
    """Every job gets a bounded timeout (the ci-job-timeout check wants one)."""
    return text.replace(
        "    runs-on: ubuntu-latest\n",
        "    runs-on: ubuntu-latest\n    timeout-minutes: 15\n",
    )


def _ci_yaml(eco_key: str) -> str:
    """Wrap the ecosystem's CI job template in a push/PR workflow — the same
    assembly the ci-exists fix uses, so the scaffold and the fix stay identical."""
    header = "name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\n\njobs:\n"
    return _with_timeout(header + ECOSYSTEMS[eco_key].ci_template)


HOUSEKEEPING_YAML = f"""\
name: housekeeping
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 7 * * 1"  # weekly drift check
  workflow_dispatch:  # the captain's "now" button

jobs:
  housekeeping:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - uses: {HOUSEKEEPING_ACTION}
"""

STRAITJACKET_YAML = f"""\
name: straitjacket
on:
  push:
    branches: [main]
  pull_request:

jobs:
  straitjacket:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      # Pinned, not main/latest: a new straitjacket rule shouldn't fail CI until
      # this repo deliberately bumps the version.
      - uses: {STRAITJACKET_ACTION}
        with:
          version: {STRAITJACKET_VERSION}
          sarif: "false"
"""

PY_TYPECHECK_YAML = """\
name: typecheck
on:
  push:
    branches: [main]
  pull_request:

jobs:
  typecheck:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run mypy src
"""


# ---- Git hooks (mirrors of .githooks/ in the fleet's own repos) --------------

HOOK_COMMIT_MSG = """\
#!/bin/sh
# Conventional-commit gate. Mirrors the `conventional` CI check (which lints the
# PR title) but applies the same rule to the commit subject, so a bad message
# fails here instead of after a push. Bypass with `git commit --no-verify`.
msg_file="$1"

# First non-blank, non-comment line is the subject.
subject=$(grep -vE '^[[:space:]]*#' "$msg_file" | grep -vE '^[[:space:]]*$' | head -n1)

# Let git's own machine-generated messages through untouched.
case "$subject" in
  "Merge "*|"Revert "*|"fixup! "*|"squash! "*) exit 0 ;;
esac

if printf '%s' "$subject" | grep -qE '^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\\([a-z0-9./_-]+\\))?!?: .+'; then
  exit 0
fi

echo "commit message must follow Conventional Commits: type(scope): summary" >&2
echo "  types: feat fix docs style refactor perf test build ci chore revert" >&2
echo "  got:   $subject" >&2
echo "  see https://www.conventionalcommits.org" >&2
exit 1
"""

HOOK_RUN_STRAITJACKET = """\
#!/bin/sh
# Run straitjacket at the SAME version this repo pins in CI, so local results
# match CI exactly regardless of what's installed globally. The version is read
# from .github/workflows/straitjacket.yml (single source of truth). Released
# binaries are cached per version under $XDG_CACHE_HOME/straitjacket/<version>/.
set -e

wf=".github/workflows/straitjacket.yml"
repo="zmaril/straitjacket"

ver=$(sed -n 's/.*version:[[:space:]]*"\\{0,1\\}\\(v[0-9][0-9.]*\\)"\\{0,1\\}.*/\\1/p' "$wf" 2>/dev/null | head -n1)
[ -n "$ver" ] || ver=$(sed -n "s|.*$repo@\\(v[0-9][0-9.]*\\).*|\\1|p" "$wf" 2>/dev/null | head -n1)
if [ -z "$ver" ]; then
  ver=$(curl -fsSLo /dev/null -w '%{url_effective}' "https://github.com/$repo/releases/latest" \\
        | sed -n 's|.*/tag/\\(v[0-9][0-9.]*\\).*|\\1|p')
fi
[ -n "$ver" ] || { echo "run-straitjacket: could not resolve version from $wf" >&2; exit 1; }

cache="${XDG_CACHE_HOME:-$HOME/.cache}/straitjacket/$ver"
bin="$cache/straitjacket"

if [ ! -x "$bin" ]; then
  os=$(uname -s); arch=$(uname -m)
  case "$os" in
    Darwin) os_part="apple-darwin" ;;
    Linux)  os_part="unknown-linux-gnu" ;;
    *) echo "run-straitjacket: unsupported OS '$os'" >&2; exit 1 ;;
  esac
  case "$arch" in
    arm64|aarch64) arch_part="aarch64" ;;
    x86_64|amd64)  arch_part="x86_64" ;;
    *) echo "run-straitjacket: unsupported arch '$arch'" >&2; exit 1 ;;
  esac
  # The release workflow only builds x86_64 for linux.
  [ "$os_part" = "unknown-linux-gnu" ] && arch_part="x86_64"
  asset="straitjacket-${arch_part}-${os_part}.tar.gz"
  url="https://github.com/$repo/releases/download/$ver/$asset"

  echo "run-straitjacket: fetching $ver ($asset)..." >&2
  mkdir -p "$cache"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$url" -o "$tmp/$asset" || { echo "run-straitjacket: download failed - $url" >&2; exit 1; }
  tar -xzf "$tmp/$asset" -C "$cache" straitjacket || { echo "run-straitjacket: extract failed" >&2; exit 1; }
  chmod +x "$bin"
fi

# No path argument: scan the working tree honoring the repo's .straitjacket.yaml
# exactly as CI does.
exec "$bin"
"""

HOOKS_README = """\
# .githooks

Committed git hooks that run this repo's CI gate locally, before a commit lands
-- so failures surface here instead of after a push.

## Activate

Hooks are not enabled automatically on clone. Run once per checkout (dev.sh does
this for you):

```sh
git config core.hooksPath .githooks
```

## What runs

`pre-commit` runs the local gate; `commit-msg` enforces Conventional Commits on
the subject line, matching the `conventional` PR-title check. `run-straitjacket`
runs straitjacket at the exact version pinned in
`.github/workflows/straitjacket.yml`, cached per version under
`$XDG_CACHE_HOME/straitjacket/<version>/`.

## Bypass

`git commit --no-verify` skips the hooks for a single commit.
"""

# The pre-commit gate is flavor-specific: it runs whatever CI's blocking code
# checks are, then straitjacket.
PRE_COMMIT_GATE = {
    "rust": "cargo fmt --check\ncargo clippy -- -D warnings\ncargo test",
    "bun": "bun run lint\nbun test",
    "python": (
        "uv run ruff check .\n"
        "uv run ruff format --check .\n"
        "uv run mypy src\n"
        "uv run pytest"
    ),
}


def _pre_commit(flavor: str) -> str:
    lines = "\n".join(f"run {cmd}" for cmd in PRE_COMMIT_GATE[flavor].splitlines())
    return f"""\
#!/bin/sh
# Local gate -- the same checks CI enforces, run before the commit lands so
# failures surface here instead of after a push. Activate with:
#   git config core.hooksPath .githooks
# Bypass with `git commit --no-verify`.
set -e
# git exports GIT_DIR/GIT_INDEX_FILE/GIT_WORK_TREE to hooks; unset them so a hook
# run sees the same world as a terminal run.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY
run() {{ printf '\\n== %s\\n' "$*"; "$@"; }}

{lines}
run ./.githooks/run-straitjacket
"""


# ---- Per-flavor dev.sh -------------------------------------------------------

DEV_INSTALL = {
    "rust": ("cargo build", "building the crate"),
    "bun": ("bun install", "installing dependencies"),
    "python": ("uv sync", "syncing the uv environment (deps + dev tooling)"),
}


def _dev_sh(name: str, flavor: str) -> str:
    cmd, blurb = DEV_INSTALL[flavor]
    return f"""\
#!/usr/bin/env bash
# Stand up the basic dev environment for {name}.
# One command a newcomer runs after cloning: install deps and wire up the hooks.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> {blurb}"
{cmd}

echo "==> enabling the committed git hooks (pre-commit + commit-msg)"
git config core.hooksPath .githooks

echo "Dev environment ready. Hooks are active (git commit --no-verify to skip)."
"""


# ---- Prose files -------------------------------------------------------------


def _readme(name: str, flavor: str) -> str:
    dev_cmd, _ = DEV_INSTALL[flavor]
    return f"""\
# {name}

One-line description of {name} goes here.

[![housekeeping](https://img.shields.io/badge/powderworks-housekeeping-blue?logo=github)](https://github.com/{OWNER}/housekeeping)

## Getting started

Clone the repo and run the dev setup script, which installs dependencies and
wires up the git hooks:

```sh
./scripts/dev.sh
```

That runs `{dev_cmd}` and points git at the committed hooks under `.githooks/`,
so the same checks CI enforces run before a commit lands.

## Usage

Describe how to use {name} here. Until then, this section is a placeholder that
keeps the README above the deterministic floor housekeeping checks for: a title,
an install section, a usage section, and license and contributing headings.

## Development

`./scripts/dev.sh` stands up the dev environment. The hooks it installs run the
project's lint, tests, and [straitjacket](https://github.com/{OWNER}/straitjacket)
locally, mirroring CI so failures surface before a push rather than after.

CI runs on every push and pull request: a build-plus-test workflow, straitjacket
over code and prose, and a conventional-commit check on the PR title.

## Contributing

Changes go branch -> pull request -> review, and {OWNER_NAME} merges. PR titles
follow [Conventional Commits](https://www.conventionalcommits.org)
(`type(scope): summary`), enforced by the `conventional` workflow in CI, so
squash-merge commits stay machine-readable on main.

This repo is a member of the powderworks fleet and audits itself with
[housekeeping](https://github.com/{OWNER}/housekeeping) on every push and pull
request. See the [design notes](notes/design.md) for the shape of the project.

## License

Released under the MIT License. See [LICENSE](LICENSE).
"""


def _agents(name: str, flavor: str) -> str:
    return f"""\
# Agent guide

How agents work in this repo. The human is {OWNER_NAME}; the taste is his.

## Pull requests

- PR titles are Conventional Commits: `type(scope): summary`, types
  `feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert`. The
  `conventional` workflow rejects anything else, and squash merges inherit the
  PR title.
- Never merge. Open the PR, get every check green, and hand {OWNER_NAME} the
  link. He reviews and merges everything himself.
- Main is protected: all changes go branch -> PR -> required checks -> review.

## Dev setup

Run `./scripts/dev.sh` once per checkout. It installs dependencies and activates
the committed git hooks, so lint, tests, and straitjacket run before each commit.

## Fleet

This repo is a member of the powderworks fleet ({FLEET}) and runs the
[housekeeping](https://github.com/{OWNER}/housekeeping) self-audit in CI. Keep it
green: fleet-locked policy (conventional commits, todos in the todo file) is not
overridable here.
"""


CLAUDE_MD = """\
# CLAUDE.md

Project guidance lives in [AGENTS.md](./AGENTS.md) -- imported below so it
applies here too.

@AGENTS.md
"""


def _design(name: str) -> str:
    return f"""\
# {name} -- Design

## Overview

Placeholder for the design of {name}: what it is, who it's for, and the shape of
the solution. This file is required for public fleet members, so it exists from
day one -- fill it in as the design settles.
"""


def _changelog() -> str:
    today = datetime.date.today().isoformat()
    return f"""\
# Changelog

Notable changes to this project, newest first, by date.

## {today}

- scaffolded the repository with `housekeeper new`
"""


def _todo(name: str) -> str:
    return (
        f"Worklist for {name}.\n\n"
        "Keep tracked tasks in this file so they stay in one place the fleet's "
        "stray-todos check can find, instead of scattered across the codebase.\n"
    )


def _housekeeping_toml(private: bool, dependabot_automerge: bool) -> str:
    lines = [
        f'fleet = "{FLEET}"',
        "",
        "[checks]",
        "# Fleet policy requires conventional commits; enforced via the "
        "conventional workflow.",
        'conventional-commits = "required"',
    ]
    if private:
        lines.append("# Private repo: no public site to keep reachable.")
        lines.append('website = "off"')
    if dependabot_automerge:
        # Declare the intent the dependabot-automerge workflow relies on: opt in
        # (dependabot = true) and turn on GitHub's repo auto-merge setting
        # (enabled = true), so the dependabot-automerge check passes.
        lines.append("")
        lines.append("[allow-auto-merge]")
        lines.append("enabled = true")
        lines.append("dependabot = true")
    return "\n".join(lines) + "\n"


def _gitignore(eco_key: str) -> str:
    patterns = list(ECOSYSTEMS[eco_key].gitignore) + [".DS_Store"]
    return "\n".join(patterns) + "\n"


def _dependabot(eco_key: str) -> str:
    ecos = [ECOSYSTEMS[eco_key].dependabot, "github-actions"]
    blocks = "\n".join(
        f'  - package-ecosystem: "{eco}"\n'
        f'    directory: "/"\n'
        f"    schedule:\n"
        f'      interval: "weekly"'
        for eco in ecos
    )
    return f"version: 2\nupdates:\n{blocks}\n"


# ---- Per-flavor manifests ----------------------------------------------------


def _package_slug(name: str) -> str:
    """A python-import-safe package name (hyphens are illegal in a module path)."""
    return name.replace("-", "_")


def _rust_files(name: str) -> dict[str, str]:
    cargo = (
        "[package]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        'edition = "2021"\n'
        "\n"
        "[dependencies]\n"
    )
    main_rs = f'fn main() {{\n    println!("hello from {name}");\n}}\n'
    return {"Cargo.toml": cargo, "src/main.rs": main_rs}


def _bun_files(name: str) -> dict[str, str]:
    package_json = (
        "{\n"
        f'  "name": "{name}",\n'
        '  "version": "0.1.0",\n'
        '  "private": true,\n'
        '  "type": "module",\n'
        '  "scripts": {\n'
        '    "test": "bun test",\n'
        '    "lint": "biome check ."\n'
        "  }\n"
        "}\n"
    )
    tsconfig = (
        "{\n"
        '  "compilerOptions": {\n'
        '    "strict": true,\n'
        '    "target": "ESNext",\n'
        '    "module": "ESNext",\n'
        '    "moduleResolution": "bundler",\n'
        '    "noEmit": true,\n'
        '    "skipLibCheck": true\n'
        "  },\n"
        '  "include": ["src"]\n'
        "}\n"
    )
    index_ts = (
        f'export function hello(): string {{\n  return "hello from {name}";\n}}\n'
    )
    return {
        "package.json": package_json,
        "tsconfig.json": tsconfig,
        "src/index.ts": index_ts,
    }


def _python_files(name: str) -> dict[str, str]:
    slug = _package_slug(name)
    pyproject = (
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        'description = "A powderworks fleet member."\n'
        'requires-python = ">=3.11"\n'
        "dependencies = []\n"
        "\n"
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n'
        "\n"
        "[tool.hatch.build.targets.wheel]\n"
        f'packages = ["src/{slug}"]\n'
        "\n"
        "[dependency-groups]\n"
        'dev = ["mypy>=1.0", "pytest>=8.0", "ruff>=0.6"]\n'
    )
    init = f'"""{name}."""\n\n__version__ = "0.1.0"\n'
    return {"pyproject.toml": pyproject, f"src/{slug}/__init__.py": init}


FLAVOR_FILES = {
    "rust": _rust_files,
    "bun": _bun_files,
    "python": _python_files,
}


def _typecheck_yaml(flavor: str) -> str | None:
    if flavor == "bun":
        return _with_timeout(BUN_TYPECHECK)
    if flavor == "python":
        return PY_TYPECHECK_YAML
    return None  # rust is compiled: it typechecks at build


# ---- The scaffold ------------------------------------------------------------


def build_files(
    name: str, flavor: str, private: bool, dependabot_automerge: bool
) -> dict[str, str]:
    """Every repo-relative path the scaffold writes, mapped to its contents."""
    eco_key = FLAVORS[flavor]
    files: dict[str, str] = {
        # Audience-facing floor.
        "LICENSE": MIT.format(year=datetime.date.today().year, name=OWNER_NAME),
        "README.md": _readme(name, flavor),
        "CHANGELOG.md": _changelog(),
        "AGENTS.md": _agents(name, flavor),
        "CLAUDE.md": CLAUDE_MD,
        "notes/design.md": _design(name),
        "todo.txt": _todo(name),
        # Housekeeping config + fleet opt-in.
        ".housekeeping.toml": _housekeeping_toml(private, dependabot_automerge),
        ".gitignore": _gitignore(eco_key),
        # Scripts + hooks.
        "scripts/dev.sh": _dev_sh(name, flavor),
        ".githooks/pre-commit": _pre_commit(flavor),
        ".githooks/commit-msg": HOOK_COMMIT_MSG,
        ".githooks/run-straitjacket": HOOK_RUN_STRAITJACKET,
        ".githooks/README.md": HOOKS_README,
        # GitHub metadata.
        ".github/CODEOWNERS": f"* @{OWNER}\n",
        ".github/dependabot.yml": _dependabot(eco_key),
        # Workflows.
        ".github/workflows/ci.yml": _ci_yaml(eco_key),
        ".github/workflows/housekeeping.yml": HOUSEKEEPING_YAML,
        ".github/workflows/straitjacket.yml": STRAITJACKET_YAML,
        ".github/workflows/conventional.yml": _with_timeout(CONVENTIONAL_WORKFLOW),
    }
    typecheck = _typecheck_yaml(flavor)
    if typecheck is not None:
        files[".github/workflows/typecheck.yml"] = typecheck
    if dependabot_automerge:
        # Reuse the check module's canonical YAML — no second copy to drift.
        files[".github/workflows/dependabot-automerge.yml"] = (
            DEPENDABOT_AUTOMERGE_WORKFLOW
        )
    files.update(FLAVOR_FILES[flavor](name))
    return files


# Paths written with the executable bit set (scripts and hooks).
_EXECUTABLE = {
    "scripts/dev.sh",
    ".githooks/pre-commit",
    ".githooks/commit-msg",
    ".githooks/run-straitjacket",
}


def _next_steps(name: str, flavor: str, dependabot_automerge: bool) -> list[str]:
    lockfile = ECOSYSTEMS[FLAVORS[flavor]].lockfile or "the lockfile"
    dev_cmd, _ = DEV_INSTALL[flavor]
    steps = [
        f"Create the repo on GitHub: gh repo create {OWNER}/{name} --source . --push",
        "Enable branch protection on main with required status checks: "
        "test, straitjacket.",
        "Enable secret scanning (and push protection) in the repo's security settings.",
        f"Run ./scripts/dev.sh to install deps and generate {lockfile} "
        f"(via {dev_cmd}); commit it -- the lockfiles check stays red until then.",
        "Fleet-managed lint configs (stylelint, vale, codespell, biome) arrive "
        "from the captain: run `housekeeper captain --sync-configs` from the "
        "powderworks checkout, not the scaffold.",
    ]
    if dependabot_automerge:
        # The workflow is only half the story: without GitHub's repo auto-merge
        # setting on AND required status checks registered, auto-merge can fire on
        # branch protection alone rather than on green CI. Say so honestly.
        steps.append(
            "dependabot auto-merge: turn on GitHub's repo auto-merge setting "
            "(or run `housekeeper fix allow-auto-merge`), and register the "
            "required status checks (test, straitjacket) so --auto actually gates "
            "on green CI -- otherwise auto-merge fires on branch protection alone."
        )
    return steps


def scaffold(
    dest: Path,
    name: str,
    flavor: str,
    private: bool = False,
    force: bool = False,
    dependabot_automerge: bool = False,
) -> ScaffoldResult:
    """Write a fleet-compliant repo skeleton into `dest`.

    Existing files are skipped and reported unless `force` is set. Returns a
    ScaffoldResult describing what was created, skipped, and what a human still
    has to do (things a scaffold honestly can't: GitHub, deps, the captain)."""
    if flavor not in FLAVORS:
        raise ValueError(f"unknown flavor {flavor!r}; choose one of {sorted(FLAVORS)}")

    result = ScaffoldResult(
        dest=dest,
        flavor=flavor,
        next_steps=_next_steps(name, flavor, dependabot_automerge),
    )
    for rel, content in build_files(
        name, flavor, private, dependabot_automerge
    ).items():
        target = dest / rel
        if target.exists() and not force:
            result.skipped.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        if rel in _EXECUTABLE:
            target.chmod(
                target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
        result.created.append(rel)
    return result

"""stylelint lints the repo's stylesheets from CI. Wiring only — findings are
stylelint's own business. Skips when the repo has no CSS to lint."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed, skipped
from .ci import workflow_files

STYLESHEET_GLOBS = ("*.css", "*.scss", "*.sass", "*.less")
# vendored trees aren't ours to lint — a stylesheet under one doesn't count.
VENDOR_DIRS = {"node_modules", ".venv", "target", "dist", "build", "vendor", ".git"}

CONFIG_NAMES = (
    ".stylelintrc",
    ".stylelintrc.json",
    ".stylelintrc.yaml",
    ".stylelintrc.yml",
    ".stylelintrc.js",
    ".stylelintrc.cjs",
    ".stylelintrc.mjs",
    "stylelint.config.js",
    "stylelint.config.cjs",
    "stylelint.config.mjs",
)


def has_stylesheets(workdir: Path) -> bool:
    for pattern in STYLESHEET_GLOBS:
        for path in workdir.rglob(pattern):
            if not any(part in VENDOR_DIRS for part in path.relative_to(workdir).parts):
                return True
    return False


def config_file(workdir: Path) -> str | None:
    for name in CONFIG_NAMES:
        if (workdir / name).is_file():
            return name
    package = workdir / "package.json"
    if package.is_file() and '"stylelint"' in package.read_text():
        return "package.json (stylelint key)"
    return None


@check("stylelint", needs=("clone",))
def stylelint(ctx: RepoContext):
    config = config_file(ctx.workdir)
    if not has_stylesheets(ctx.workdir) and config is None:
        return skipped("no stylesheets to lint")
    if config is None:
        return failed("stylesheets present but no stylelint config")
    files = workflow_files(ctx.workdir)
    wired = [p.name for p in files if "stylelint" in p.read_text().lower()]
    if not wired:
        return failed(f"stylelint config ({config}) but no CI workflow runs it")
    return passed(f"stylelint ({config}) runs in: {', '.join(wired)}")


CONFIG = """\
{
  "extends": ["stylelint-config-standard"]
}
"""

WORKFLOW = """\
name: stylelint
on:
  push:
    branches: [main]
  pull_request:

jobs:
  stylelint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: lts/*
      - run: npx --yes stylelint "**/*.{css,scss,sass,less}"
"""


@fix_for("stylelint")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        changed = []
        if config_file(workdir) is None:
            config = workdir / ".stylelintrc.json"
            config.write_text(CONFIG)
            changed.append(config)
        workflow = workdir / ".github" / "workflows" / "stylelint.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(WORKFLOW)
        changed.append(workflow)
        return changed

    apply_file_fix(
        ctx,
        "stylelint",
        describe="add a .stylelintrc.json (if missing) and a workflow running "
        "stylelint on push + PR",
        why="lints the repo's stylesheets on every push and PR, so CSS mistakes "
        "get caught at review time instead of shipping",
        write_changes=write,
        commit_message="ci: run stylelint",
    )

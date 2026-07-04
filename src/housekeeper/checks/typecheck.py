"""TypeScript repos must actually run a typechecker in CI.

Compiled ecosystems (cargo, go) typecheck at build; TypeScript is the one
where lint and tests can stay green while the types rot — biome and eslint
do not typecheck. Scoped to TS on purpose; other gradually-typed ecosystems
can join when there's a repo that needs it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..context import RepoContext, run
from ..fixing import apply_file_fix, console
from ..registry import check, failed, fix_for, passed, skipped
from .ci import resolve_package_scripts, workflow_files

TYPECHECK = re.compile(r"\b(tsc|vue-tsc|tsgo|typecheck)\b")


@check("typecheck", needs=("clone",))
def typecheck(ctx: RepoContext):
    if not (ctx.workdir / "tsconfig.json").is_file():
        return skipped("no tsconfig.json — compiled ecosystems typecheck at build")
    text = "\n".join(p.read_text(errors="replace") for p in workflow_files(ctx.workdir))
    text += "\n" + resolve_package_scripts(ctx.workdir, text)
    if TYPECHECK.search(text):
        return passed("CI runs a TypeScript typechecker")
    return failed("TypeScript repo but CI never runs tsc",
                  note="lint and tests pass while types rot — the silent failure mode")


WORKFLOWS = {
    "bun": """\
name: typecheck
on:
  push:
    branches: [main]
  pull_request:

jobs:
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
      - run: bun install --frozen-lockfile
      - run: bunx tsc --noEmit
""",
    "npm": """\
name: typecheck
on:
  push:
    branches: [main]
  pull_request:

jobs:
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npx tsc --noEmit
""",
}


@fix_for("typecheck")
def fix(ctx: RepoContext):
    runner = "bun" if any(e.name == "bun" for e in ctx.ecosystems) else "npm"

    # Preflight so the first red CI run isn't a surprise.
    tool = ("bunx", "tsc", "--noEmit") if runner == "bun" else ("npx", "tsc", "--noEmit")
    if shutil.which(tool[0]):
        proc = run(list(tool), cwd=ctx.workdir)
        errors = len(re.findall(r"error TS\d+", proc.stdout + proc.stderr))
        if errors:
            console.print(f"[yellow]heads up: tsc currently finds {errors} error(s) here — "
                          f"CI will be red until they're fixed[/yellow]")

    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "typecheck.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(WORKFLOWS[runner])
        return [target]

    apply_file_fix(
        ctx, "typecheck",
        describe=f"add .github/workflows/typecheck.yml running tsc --noEmit via {runner}",
        why="biome/eslint don't typecheck — without tsc in CI, type errors merge "
            "silently and pile up until someone runs the compiler by hand",
        write_changes=write,
        commit_message="ci: typecheck with tsc --noEmit",
    )

"""If the language supports typechecking, it should be on and running in CI.

Compiled ecosystems (cargo, go) typecheck at build. Everything else with an
optional type layer — TypeScript, JavaScript, Python, Clojure — can stay
green in lint and tests while the types rot. House rule: the options exist,
use them.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..context import RepoContext, run
from ..fixing import apply_file_fix, console
from ..registry import check, failed, fix_for, passed, skipped
from .ci import resolve_package_scripts, workflow_files

SIGNALS = {
    "typescript": re.compile(r"\b(tsc|vue-tsc|tsgo|typecheck|astro check)\b"),
    "python": re.compile(r"\b(mypy|pyright|basedpyright|pyre|pytype|pyrefly|ty check)\b"),
    "clojure": re.compile(r"\b(clj-kondo|core\.typed|typedclojure)\b"),
}

GUIDANCE = {
    "typescript": "run tsc (or vue-tsc / astro check) in CI",
    "python": "run mypy / pyright / ty in CI",
    "clojure": "run clj-kondo (or core.typed) in CI",
}


def typed_languages(workdir: Path) -> list[str]:
    langs = []
    if (workdir / "tsconfig.json").is_file() or (workdir / "jsconfig.json").is_file():
        langs.append("typescript")
    elif (workdir / "package.json").is_file():
        langs.append("javascript-untyped")
    if (workdir / "pyproject.toml").is_file() or (workdir / "requirements.txt").is_file():
        langs.append("python")
    if (workdir / "deps.edn").is_file() or (workdir / "project.clj").is_file():
        langs.append("clojure")
    return langs


@check("typecheck", needs=("clone",))
def typecheck(ctx: RepoContext):
    langs = typed_languages(ctx.workdir)
    if not langs:
        return skipped("no optionally-typed languages detected",
                       note="compiled ecosystems typecheck at build")

    text = "\n".join(p.read_text(errors="replace") for p in workflow_files(ctx.workdir))
    text += "\n" + resolve_package_scripts(ctx.workdir, text)

    problems, covered = [], []
    for lang in langs:
        if lang == "javascript-untyped":
            problems.append("javascript with no type layer — add a tsconfig/jsconfig "
                            "(checkJs counts) and then typecheck it in CI")
        elif SIGNALS[lang].search(text):
            covered.append(lang)
        else:
            problems.append(f"{lang}: CI never typechecks — {GUIDANCE[lang]}")

    if problems:
        return failed("; ".join(problems),
                      note="lint and tests pass while types rot — the silent failure mode")
    return passed(f"typechecking runs in CI: {', '.join(covered)}")


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
    langs = typed_languages(ctx.workdir)
    if "typescript" not in langs:
        # Picking a Python/Clojure typechecker and its config is a taste
        # decision; the check's guidance says which tools qualify.
        console.print("[yellow]no automated fix for this language mix — see the check's "
                      "guidance for which typecheckers count[/yellow]")
        return

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

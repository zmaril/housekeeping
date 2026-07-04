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
from ..languages import ECOSYSTEMS, TYPED_LANGUAGES
from ..registry import check, failed, fix_for, passed, skipped
from .ci import resolve_package_scripts, workflow_files


def _has_marker(workdir: Path, lang: str) -> bool:
    return any((workdir / m).is_file() for m in TYPED_LANGUAGES[lang].markers)


def typed_languages(workdir: Path) -> list[str]:
    langs = []
    if _has_marker(workdir, "typescript"):
        langs.append("typescript")
    elif (workdir / "package.json").is_file():
        langs.append("javascript-untyped")
    if _has_marker(workdir, "python"):
        langs.append("python")
    if _has_marker(workdir, "clojure"):
        langs.append("clojure")
    return langs


@check("typecheck", needs=("clone",))
def typecheck(ctx: RepoContext):
    langs = typed_languages(ctx.workdir)
    if not langs:
        return skipped(
            "no optionally-typed languages detected",
            note="compiled ecosystems typecheck at build",
        )

    text = "\n".join(p.read_text(errors="replace") for p in workflow_files(ctx.workdir))
    text += "\n" + resolve_package_scripts(ctx.workdir, text)

    problems, covered = [], []
    for lang in langs:
        if lang == "javascript-untyped":
            problems.append(
                "javascript with no type layer — add a tsconfig/jsconfig "
                "(checkJs counts) and then typecheck it in CI"
            )
        elif TYPED_LANGUAGES[lang].signal.search(text):
            covered.append(lang)
        else:
            problems.append(
                f"{lang}: CI never typechecks — {TYPED_LANGUAGES[lang].guidance}"
            )

    if problems:
        return failed(
            "; ".join(problems),
            note="lint and tests pass while types rot — the silent failure mode",
        )
    return passed(f"typechecking runs in CI: {', '.join(covered)}")


@fix_for("typecheck")
def fix(ctx: RepoContext):
    langs = typed_languages(ctx.workdir)
    if "typescript" not in langs:
        # Picking a Python/Clojure typechecker and its config is a taste
        # decision; the check's guidance says which tools qualify.
        console.print(
            "[yellow]no automated fix for this language mix — see the check's "
            "guidance for which typecheckers count[/yellow]"
        )
        return

    # The typecheck workflow template lives on the JS ecosystem (languages.py);
    # bun if this repo uses it, else the npm template.
    runner = "bun" if any(e.name == "bun" for e in ctx.ecosystems) else "npm"
    workflow = ECOSYSTEMS[runner].typecheck_template

    # Preflight so the first red CI run isn't a surprise.
    tool = (
        ("bunx", "tsc", "--noEmit") if runner == "bun" else ("npx", "tsc", "--noEmit")
    )
    if shutil.which(tool[0]):
        proc = run(list(tool), cwd=ctx.workdir)
        errors = len(re.findall(r"error TS\d+", proc.stdout + proc.stderr))
        if errors:
            console.print(
                f"[yellow]heads up: tsc currently finds {errors} error(s) here — "
                f"CI will be red until they're fixed[/yellow]"
            )

    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "typecheck.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(workflow)
        return [target]

    apply_file_fix(
        ctx,
        "typecheck",
        describe=f"add .github/workflows/typecheck.yml running tsc --noEmit via {runner}",
        why="biome/eslint don't typecheck — without tsc in CI, type errors merge "
        "silently and pile up until someone runs the compiler by hand",
        write_changes=write,
        commit_message="ci: typecheck with tsc --noEmit",
    )

"""Committed codegen output can't drift: CI regenerates and diffs to zero.

Repos declare their regen commands in .housekeeping.toml:

    [[codegen]]
    name = "ruby bindings"
    command = "make bindgen"

The check is wiring-only (like straitjacket): CI must run each declared
command and assert a clean tree afterward (git diff --exit-code or kin).
Housekeeping never runs the regen itself — toolchains vary too much.
"""

from __future__ import annotations

import re

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .ci import resolve_package_scripts, workflow_files

DIFF_GUARD = re.compile(r"git diff (--exit-code|--quiet)|git status --porcelain")


@check("codegen-drift", needs=("clone",))
def codegen_drift(ctx: RepoContext):
    entries = ctx.config.codegen
    if not entries:
        return skipped(
            "no [[codegen]] entries declared",
            note="repos with committed generated code declare regen commands "
            "in .housekeeping.toml so CI can prove zero drift",
        )

    text = "\n".join(p.read_text(errors="replace") for p in workflow_files(ctx.workdir))
    text += "\n" + resolve_package_scripts(ctx.workdir, text)
    normalized = " ".join(text.split())

    problems, covered = [], []
    for entry in entries:
        command = str(entry.get("command", "")).strip()
        name = str(entry.get("name", command or "unnamed"))
        if not command:
            problems.append(f"codegen entry {name!r} has no command")
            continue
        if " ".join(command.split()) not in normalized:
            problems.append(f"{name}: CI never runs {command!r}")
        else:
            covered.append(name)
    if covered and not DIFF_GUARD.search(text):
        problems.append(
            "regen runs but nothing asserts zero drift afterward "
            "(add git diff --exit-code)"
        )

    if problems:
        return failed(
            "; ".join(problems),
            note="committed generated code that CI never regenerates is drift "
            "waiting to be shipped",
        )
    return passed(f"CI regenerates and zero-diffs: {', '.join(covered)}")

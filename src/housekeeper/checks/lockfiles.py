"""Every manifest has its lockfile committed and in sync, verified with native tools."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..context import RepoContext, run
from ..fixing import apply_file_fix, console
from ..registry import check, failed, fix_for, passed, skipped

# The sync-check / regen commands and the tool binary now live on the Ecosystem
# (languages.py) — read them off `eco.lock_check` / `eco.lock_regen` / `eco.tool`.


def tracked(workdir: Path, filename: str) -> bool:
    proc = run(["git", "ls-files", "--error-unmatch", filename], cwd=workdir)
    return proc.returncode == 0


@check("lockfiles", needs=("clone",))
def lockfiles(ctx: RepoContext):
    relevant = [e for e in ctx.ecosystems if e.lockfile]
    if not relevant:
        return skipped("no ecosystems with lockfiles detected")

    problems, unverified, ok = [], [], []
    for eco in relevant:
        lockfile = eco.lockfile
        if lockfile is None:  # relevant is pre-filtered; this narrows the type
            continue
        lock = ctx.workdir / lockfile
        if not lock.is_file():
            problems.append(f"{eco.name}: {lockfile} missing")
            continue
        if not tracked(ctx.workdir, lockfile):
            problems.append(f"{eco.name}: {lockfile} exists but is not committed")
            continue
        if not eco.lock_check or not eco.tool:
            unverified.append(f"{eco.name} (no sync command known)")
            continue
        if not shutil.which(eco.tool):
            unverified.append(f"{eco.name} ({eco.tool} not installed)")
            continue
        proc = run(list(eco.lock_check), cwd=ctx.workdir)
        if proc.returncode != 0:
            problems.append(
                f"{eco.name}: {eco.lockfile} out of sync with {eco.manifest}"
            )
        else:
            ok.append(eco.name)

    note = f"sync unverified for: {', '.join(unverified)}" if unverified else ""
    if problems:
        return failed("; ".join(problems), note)
    return passed(
        f"lockfiles committed and in sync: {', '.join(ok) or 'presence only'}", note
    )


@fix_for("lockfiles")
def fix(ctx: RepoContext):
    stale = []
    for eco in ctx.ecosystems:
        if not eco.lockfile:
            continue
        lock = ctx.workdir / eco.lockfile
        if not eco.lock_check or not eco.tool or not shutil.which(eco.tool):
            continue
        if not lock.is_file() or run(list(eco.lock_check), cwd=ctx.workdir).returncode:
            stale.append(eco)
    if not stale:
        console.print(
            "[yellow]nothing regenerable found (missing tools?) — fix by hand[/yellow]"
        )
        return

    def write(workdir: Path) -> list[Path]:
        changed = []
        for eco in stale:
            lockfile = eco.lockfile
            if lockfile is None:
                continue
            proc = run(list(eco.lock_regen), cwd=workdir)
            if proc.returncode != 0:
                console.print(
                    f"[red]{eco.name} regen failed:[/red] {proc.stderr.strip()[:500]}"
                )
                continue
            changed.append(workdir / lockfile)
        return changed

    apply_file_fix(
        ctx,
        "lockfiles",
        describe=f"regenerate lockfiles for: {', '.join(e.name for e in stale)}",
        why="a committed, in-sync lockfile means every machine and CI run installs "
        "the exact same versions — out-of-sync lockfiles are how 'works on my "
        "machine' happens",
        write_changes=write,
        commit_message="chore: regenerate lockfiles",
    )

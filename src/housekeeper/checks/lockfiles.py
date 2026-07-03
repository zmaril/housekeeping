"""Every manifest has its lockfile committed and in sync, verified with native tools."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..context import RepoContext, run
from ..fixing import apply_file_fix, console
from ..registry import check, failed, fix_for, passed, skipped

# tool → (sync-check command, regen command)
COMMANDS = {
    "cargo": (["cargo", "metadata", "--locked", "--format-version", "1"],
              ["cargo", "metadata", "--format-version", "1"]),
    "bun": (["bun", "install", "--frozen-lockfile", "--dry-run"],
            ["bun", "install"]),
    "npm": (["npm", "ci", "--dry-run", "--ignore-scripts"],
            ["npm", "install", "--package-lock-only"]),
    "pnpm": (["pnpm", "install", "--frozen-lockfile", "--lockfile-only"],
             ["pnpm", "install", "--lockfile-only"]),
    "yarn": (["yarn", "install", "--immutable", "--mode=skip-build"],
             ["yarn", "install", "--mode=skip-build"]),
    "uv": (["uv", "lock", "--check"], ["uv", "lock"]),
}

TOOL = {"cargo": "cargo", "bun": "bun", "npm": "npm", "pnpm": "pnpm",
        "yarn": "yarn", "uv": "uv", "go": "go"}


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
        lock = ctx.workdir / eco.lockfile
        if not lock.is_file():
            problems.append(f"{eco.name}: {eco.lockfile} missing")
            continue
        if not tracked(ctx.workdir, eco.lockfile):
            problems.append(f"{eco.name}: {eco.lockfile} exists but is not committed")
            continue
        tool = TOOL.get(eco.name)
        command = COMMANDS.get(eco.name)
        if not command or not tool or not shutil.which(tool):
            unverified.append(f"{eco.name} ({tool or '?'} not installed)")
            continue
        proc = run(command[0], cwd=ctx.workdir)
        if proc.returncode != 0:
            problems.append(f"{eco.name}: {eco.lockfile} out of sync with {eco.manifest}")
        else:
            ok.append(eco.name)

    note = f"sync unverified for: {', '.join(unverified)}" if unverified else ""
    if problems:
        return failed("; ".join(problems), note)
    return passed(f"lockfiles committed and in sync: {', '.join(ok) or 'presence only'}", note)


@fix_for("lockfiles")
def fix(ctx: RepoContext):
    stale = []
    for eco in ctx.ecosystems:
        if not eco.lockfile:
            continue
        lock = ctx.workdir / eco.lockfile
        command = COMMANDS.get(eco.name)
        tool = TOOL.get(eco.name)
        if not command or not tool or not shutil.which(tool):
            continue
        if not lock.is_file() or run(command[0], cwd=ctx.workdir).returncode != 0:
            stale.append(eco)
    if not stale:
        console.print("[yellow]nothing regenerable found (missing tools?) — fix by hand[/yellow]")
        return

    def write(workdir: Path) -> list[Path]:
        changed = []
        for eco in stale:
            proc = run(COMMANDS[eco.name][1], cwd=workdir)
            if proc.returncode != 0:
                console.print(f"[red]{eco.name} regen failed:[/red] {proc.stderr.strip()[:500]}")
                continue
            changed.append(workdir / eco.lockfile)
        return changed

    apply_file_fix(
        ctx, "lockfiles",
        describe=f"regenerate lockfiles for: {', '.join(e.name for e in stale)}",
        why="a committed, in-sync lockfile means every machine and CI run installs "
            "the exact same versions — out-of-sync lockfiles are how 'works on my "
            "machine' happens",
        write_changes=write,
        commit_message="chore: regenerate lockfiles",
    )

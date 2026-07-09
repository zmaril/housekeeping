"""Every manifest has its lockfile committed and in sync.

Sync is verified with the ecosystem's native tool where one exists (cargo, uv,
bun, npm, …). Ecosystems with no native sync check (ruby, go) fall back to a
git-history heuristic: a lockfile whose manifest was committed in a strictly
later commit is likely stale. The output stays honest about which ecosystems
were natively verified versus only checked by the heuristic.
"""

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


def gitignored(workdir: Path, filename: str) -> bool:
    return run(["git", "check-ignore", "-q", filename], cwd=workdir).returncode == 0


def last_commit_ts(workdir: Path, path: str) -> int | None:
    """Committer timestamp of the file's most recent commit, or None if unknown."""
    out = run(
        ["git", "log", "-1", "--format=%ct", "--", path], cwd=workdir
    ).stdout.strip()
    return int(out) if out.isdigit() else None


def manifest_newer(workdir: Path, manifest: str, lockfile: str) -> bool | None:
    """True if the manifest was committed in a strictly later commit than the
    lockfile (a staleness heuristic for ecosystems with no native sync check).
    None if either timestamp can't be read."""
    m = last_commit_ts(workdir, manifest)
    lock = last_commit_ts(workdir, lockfile)
    if m is None or lock is None:
        return None
    return m > lock


@check("lockfiles", needs=("clone",))
def lockfiles(ctx: RepoContext):
    relevant = [e for e in ctx.ecosystems if e.lockfile]
    if not relevant:
        return skipped("no ecosystems with lockfiles detected")

    problems, unverified, native_ok, heuristic_ok = [], [], [], []
    for eco in relevant:
        lockfile = eco.lockfile
        if lockfile is None:  # relevant is pre-filtered; this narrows the type
            continue
        lock = ctx.workdir / lockfile
        if not lock.is_file():
            problems.append(f"{eco.name}: {lockfile} missing")
            continue
        if not tracked(ctx.workdir, lockfile):
            if gitignored(ctx.workdir, lockfile):
                problems.append(
                    f"{eco.name}: {lockfile} exists but is gitignored - commit it"
                )
            else:
                problems.append(f"{eco.name}: {lockfile} exists but is not committed")
            continue
        native = (
            bool(eco.lock_check)
            and eco.tool is not None
            and shutil.which(eco.tool) is not None
        )
        if native:
            proc = run(list(eco.lock_check), cwd=ctx.workdir)
            if proc.returncode != 0:
                problems.append(
                    f"{eco.name}: {eco.lockfile} out of sync with {eco.manifest}"
                )
            else:
                native_ok.append(eco.name)
            continue
        stale = manifest_newer(ctx.workdir, eco.manifest, lockfile)
        if stale is True:
            problems.append(
                f"{eco.name}: {eco.manifest} committed after {lockfile} - "
                "likely stale (git-history heuristic; regenerate the lockfile)"
            )
        elif stale is False:
            heuristic_ok.append(eco.name)
        else:
            unverified.append(f"{eco.name} (no native check; git history unreadable)")

    note = f"sync unverified for: {', '.join(unverified)}" if unverified else ""
    if problems:
        return failed("; ".join(problems), note)
    parts = []
    if native_ok:
        parts.append(f"native-verified in sync: {', '.join(native_ok)}")
    if heuristic_ok:
        parts.append(f"present, not stale by git history: {', '.join(heuristic_ok)}")
    details = "; ".join(parts) or "lockfiles present"
    return passed(details, note)


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

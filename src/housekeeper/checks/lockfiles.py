"""Every manifest has its lockfile committed and in sync.

Sync is verified with the ecosystem's native tool where one exists (cargo, uv,
bun, npm, …). Ecosystems with no native sync check (ruby, go) fall back to a
git-history heuristic: a lockfile whose manifest was committed in a strictly
later commit is likely stale. The output stays honest about which ecosystems
were natively verified versus only checked by the heuristic.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

from ..context import RepoContext, run
from ..fixing import apply_file_fix, console
from ..registry import check, failed, fix_for, passed, skipped

# Manifest keys that hold dependencies, per manifest filename. A package whose
# manifest declares none of these can't have a lockfile: bun deletes an empty one
# outright ("No packages! Deleted empty lockfile"), and npm/uv would only write a
# stub pinning nothing. Demanding one there is unsatisfiable, so such a package is
# skipped rather than failed.
DEPENDENCY_KEYS: dict[str, tuple[str, ...]] = {
    "package.json": (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ),
    "Cargo.toml": ("dependencies", "dev-dependencies", "build-dependencies"),
}

# The sync-check / regen commands and the tool binary now live on the Ecosystem
# (languages.py) — read them off `eco.lock_check` / `eco.lock_regen` / `eco.tool`.


def _label(eco) -> str:
    """The ecosystem's name, tagged with its directory when it isn't the root, so a
    problem/ok line reads `bun (crates/entl-node): ...` for a nested package."""
    return f"{eco.name} ({eco.dir})" if eco.dir else eco.name


def _rel(eco, filename: str) -> str:
    """A repo-relative posix path for a file in the ecosystem's directory, for git."""
    return (Path(eco.dir) / filename).as_posix() if eco.dir else filename


def declares_dependencies(manifest_path: Path, manifest_name: str) -> bool | None:
    """Whether a manifest declares any dependency.

    Returns None when it can't be determined — an unparseable or unrecognized
    manifest defaults to "assume it has dependencies", so an unreadable file
    never silently downgrades the check.
    """
    if not manifest_path.is_file():
        return None
    try:
        if manifest_name == "package.json":
            data = json.loads(manifest_path.read_text())
        elif manifest_name in ("Cargo.toml", "pyproject.toml"):
            data = tomllib.loads(manifest_path.read_text())
        else:
            return None
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None

    if manifest_name == "pyproject.toml":
        project = data.get("project", {})
        poetry = data.get("tool", {}).get("poetry", {})
        buckets = [
            project.get("dependencies"),
            project.get("optional-dependencies"),
            data.get("dependency-groups"),
            # poetry always lists `python` itself, so it counts only past one entry
            {k: v for k, v in (poetry.get("dependencies") or {}).items() if k != "python"},
            poetry.get("group"),
        ]
        return any(bool(b) for b in buckets)

    return any(bool(data.get(key)) for key in DEPENDENCY_KEYS.get(manifest_name, ()))


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

    # A repo can exempt directories it deliberately keeps lockfile-free, e.g. a
    # scratch/spike package, or one whose lockfile is intentionally gitignored:
    #   [lockfiles]
    #   ignore = ["spike", "crates/demo"]
    ignored_dirs = {
        str(d).strip("/") for d in ctx.config.section("lockfiles").get("ignore", [])
    }

    problems, unverified, native_ok, heuristic_ok = [], [], [], []
    skipped_pkgs = []
    for eco in relevant:
        lockfile = eco.lockfile
        if lockfile is None:  # relevant is pre-filtered; this narrows the type
            continue
        label = _label(eco)
        if str(eco.dir).strip("/") in ignored_dirs:
            skipped_pkgs.append(f"{label} (ignored by config)")
            continue
        lock_rel = _rel(eco, lockfile)
        lock = ctx.workdir / eco.dir / lockfile
        if not lock.is_file():
            # No lockfile *and* no dependencies to lock: unsatisfiable, not a failure.
            if (
                declares_dependencies(
                    ctx.workdir / eco.dir / eco.manifest, eco.manifest
                )
                is False
            ):
                skipped_pkgs.append(f"{label} (no dependencies declared)")
                continue
            problems.append(f"{label}: {lockfile} missing")
            continue
        if not tracked(ctx.workdir, lock_rel):
            if gitignored(ctx.workdir, lock_rel):
                problems.append(
                    f"{label}: {lockfile} exists but is gitignored - commit it"
                )
            else:
                problems.append(f"{label}: {lockfile} exists but is not committed")
            continue
        native = (
            bool(eco.lock_check)
            and eco.tool is not None
            and shutil.which(eco.tool) is not None
        )
        if native:
            # The native tool must run in the package dir, where its manifest lives.
            proc = run(list(eco.lock_check), cwd=ctx.workdir / eco.dir)
            if proc.returncode != 0:
                problems.append(
                    f"{label}: {eco.lockfile} out of sync with {eco.manifest}"
                )
            else:
                native_ok.append(label)
            continue
        stale = manifest_newer(ctx.workdir, _rel(eco, eco.manifest), lock_rel)
        if stale is True:
            problems.append(
                f"{label}: {eco.manifest} committed after {lockfile} - "
                "likely stale (git-history heuristic; regenerate the lockfile)"
            )
        elif stale is False:
            heuristic_ok.append(label)
        else:
            unverified.append(f"{label} (no native check; git history unreadable)")

    notes = []
    if unverified:
        notes.append(f"sync unverified for: {', '.join(unverified)}")
    # Never let a skip pass silently — a skipped package still shows up in the note.
    if skipped_pkgs:
        notes.append(f"not graded: {', '.join(skipped_pkgs)}")
    note = "; ".join(notes)
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
        lock = ctx.workdir / eco.dir / eco.lockfile
        if not eco.lock_check or not eco.tool or not shutil.which(eco.tool):
            continue
        if (
            not lock.is_file()
            or run(list(eco.lock_check), cwd=ctx.workdir / eco.dir).returncode
        ):
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
            proc = run(list(eco.lock_regen), cwd=workdir / eco.dir)
            if proc.returncode != 0:
                console.print(
                    f"[red]{_label(eco)} regen failed:[/red] {proc.stderr.strip()[:500]}"
                )
                continue
            changed.append(workdir / eco.dir / lockfile)
        return changed

    apply_file_fix(
        ctx,
        "lockfiles",
        describe=f"regenerate lockfiles for: {', '.join(_label(e) for e in stale)}",
        why="a committed, in-sync lockfile means every machine and CI run installs "
        "the exact same versions — out-of-sync lockfiles are how 'works on my "
        "machine' happens",
        write_changes=write,
        commit_message="chore: regenerate lockfiles",
    )

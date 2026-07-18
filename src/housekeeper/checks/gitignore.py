"""Each ecosystem's build junk is ignored by a .gitignore on its path."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, passed, fix_for, skipped

# The build-junk patterns each ecosystem should ignore live on the Ecosystem
# (languages.py) — read them off `eco.gitignore`.


def _read_patterns(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {line.strip().lstrip("/") for line in path.read_text().splitlines()}


def _covered(pattern: str, have: set[str]) -> bool:
    # Trailing-slash-insensitive match against lines already stripped + lstripped
    # of a leading slash: `/target`, `target`, and `target/` all cover `target/`.
    return pattern in have or pattern.rstrip("/") in have


def _applicable_gitignores(workdir: Path, reldir: str) -> list[Path]:
    """The `.gitignore` files git would apply to an ecosystem at `reldir`: the
    repo-root ignore, then each ancestor directory down to and including the
    instance's own dir. Git ignore rules are inherited down the tree, so a pattern
    in ANY of these covers the instance's build junk (e.g. for `crates/entl-node`:
    `./.gitignore`, `crates/.gitignore`, `crates/entl-node/.gitignore`)."""
    paths = [workdir / ".gitignore"]
    cur = workdir
    for part in Path(reldir).parts if reldir else ():
        cur = cur / part
        paths.append(cur / ".gitignore")
    return paths


def _missing(ctx: RepoContext) -> list[tuple[str, str]]:
    """Build-junk patterns not covered by any applicable `.gitignore`, as
    (pattern, dir) pairs. Deduped by (pattern, dir): a pattern needed by several
    instances in the same dir is reported once, but a pattern covered for one
    instance's dir and uncovered for another's is reported against the dir where
    it's genuinely missing."""
    missing: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for eco in ctx.ecosystems:
        if not eco.gitignore:
            continue
        have: set[str] = set()
        for path in _applicable_gitignores(ctx.workdir, eco.dir):
            have |= _read_patterns(path)
        for pattern in eco.gitignore:
            if _covered(pattern, have):
                continue
            key = (pattern, eco.dir)
            if key not in seen:
                seen.add(key)
                missing.append(key)
    return missing


def missing_patterns(ctx: RepoContext) -> list[str]:
    """The distinct still-uncovered patterns — what the fix appends to the root
    `.gitignore` (a root pattern is recursive, so it covers every instance)."""
    return sorted({pattern for pattern, _ in _missing(ctx)})


def _describe(missing: list[tuple[str, str]]) -> str:
    return ", ".join(
        f"{pattern} ({dir})" if dir else pattern for pattern, dir in missing
    )


@check("gitignore", needs=("clone",))
def gitignore(ctx: RepoContext):
    if not any(e.gitignore for e in ctx.ecosystems):
        return skipped("no ecosystems with known build junk detected")
    missing = _missing(ctx)
    if missing:
        return failed(f".gitignore missing: {_describe(missing)}")
    return passed(".gitignore covers ecosystem build junk")


@fix_for("gitignore")
def fix(ctx: RepoContext):
    missing = missing_patterns(ctx)
    if not missing:
        return

    def write(workdir: Path) -> list[Path]:
        path = workdir / ".gitignore"
        existing = path.read_text().rstrip("\n") + "\n" if path.is_file() else ""
        path.write_text(existing + "\n".join(missing) + "\n")
        return [path]

    apply_file_fix(
        ctx,
        "gitignore",
        describe=f"add to .gitignore: {', '.join(missing)}",
        why="build junk that isn't ignored ends up committed sooner or later — "
        "bloating the repo and burying real diffs",
        write_changes=write,
        commit_message="chore: cover build junk in .gitignore",
    )

""".gitignore exists and covers each ecosystem's build junk."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, passed, fix_for, skipped

# The build-junk patterns each ecosystem should ignore live on the Ecosystem
# (languages.py) — read them off `eco.gitignore`.


def missing_patterns(ctx: RepoContext) -> list[str]:
    path = ctx.workdir / ".gitignore"
    have = set()
    if path.is_file():
        have = {line.strip().lstrip("/") for line in path.read_text().splitlines()}
    # Git ignore patterns are recursive, so a root `node_modules/` already covers a
    # nested `crates/x-node/node_modules/`. Collect the deduped set of patterns across
    # ALL ecosystem instances (root and nested) and require them in the root ignore.
    wanted = {pattern for eco in ctx.ecosystems for pattern in eco.gitignore}
    missing = [
        pattern
        for pattern in wanted
        if pattern not in have and pattern.rstrip("/") not in have
    ]
    return sorted(set(missing))


@check("gitignore", needs=("clone",))
def gitignore(ctx: RepoContext):
    if not any(e.gitignore for e in ctx.ecosystems):
        return skipped("no ecosystems with known build junk detected")
    if not (ctx.workdir / ".gitignore").is_file():
        return failed("no .gitignore")
    missing = missing_patterns(ctx)
    if missing:
        return failed(f".gitignore missing: {', '.join(missing)}")
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

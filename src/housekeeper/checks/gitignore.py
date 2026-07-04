""".gitignore exists and covers each ecosystem's build junk."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, passed, fix_for, skipped

# ecosystem name → patterns its .gitignore should carry
WANTED = {
    "cargo": ["target/"],
    "bun": ["node_modules/"],
    "npm": ["node_modules/"],
    "pnpm": ["node_modules/"],
    "yarn": ["node_modules/"],
    "uv": [".venv/", "__pycache__/"],
    "pip": [".venv/", "__pycache__/"],
}


def missing_patterns(ctx: RepoContext) -> list[str]:
    path = ctx.workdir / ".gitignore"
    have = set()
    if path.is_file():
        have = {line.strip().lstrip("/") for line in path.read_text().splitlines()}
    missing = []
    for eco in ctx.ecosystems:
        for pattern in WANTED.get(eco.name, []):
            if pattern not in have and pattern.rstrip("/") not in have:
                missing.append(pattern)
    return sorted(set(missing))


@check("gitignore", needs=("clone",))
def gitignore(ctx: RepoContext):
    if not any(WANTED.get(e.name) for e in ctx.ecosystems):
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

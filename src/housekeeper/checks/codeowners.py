"""codeowners: a CODEOWNERS file routes review to whoever knows the code.

Without it, review falls to whoever happens to be around, and changes land in
sensitive areas with nobody who understands them on the hook. A CODEOWNERS with at
least one real rule wires review (and, with branch protection, required review) to
the right people. Recommended rather than required: on a solo repo it's ceremony, so
it softens — and any repo can turn it off in `.housekeeping.toml`.
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed

# GitHub honours CODEOWNERS in these three locations, in this order.
LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def codeowners_path(workdir: Path) -> Path | None:
    for rel in LOCATIONS:
        path = workdir / rel
        if path.is_file():
            return path
    return None


def has_rule(path: Path) -> bool:
    """At least one non-comment, non-blank line — an actual ownership rule."""
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


@check("codeowners", needs=("clone",))
def codeowners(ctx: RepoContext):
    path = codeowners_path(ctx.workdir)
    if path is None:
        return failed("no CODEOWNERS file")
    if not has_rule(path):
        rel = path.relative_to(ctx.workdir)
        return failed(f"{rel} has no ownership rules (only comments/blanks)")
    return passed(f"{path.relative_to(ctx.workdir)} present with ownership rules")


@fix_for("codeowners")
def fix(ctx: RepoContext):
    owner = ctx.repo.split("/", 1)[0]

    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "CODEOWNERS"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# Every file, unless a later rule overrides, is owned by:\n* @{owner}\n"
        )
        return [target]

    apply_file_fix(
        ctx,
        "codeowners",
        describe=f"add .github/CODEOWNERS with a catch-all rule (* @{owner})",
        why="CODEOWNERS routes review to whoever knows the code; a catch-all owner is "
        "the floor — narrow it per-directory as the team grows",
        write_changes=write,
        commit_message="chore: add CODEOWNERS",
    )

"""A changelog file exists. Presence only, by policy — versions, dates, or
freeform are all fine; we don't police format, only that changes get written
down somewhere findable."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed

CANDIDATES = ("CHANGELOG.md", "CHANGELOG", "CHANGELOG.txt", "CHANGES.md", "HISTORY.md")


@check("changelog", needs=("clone",))
def changelog(ctx: RepoContext):
    for name in CANDIDATES:
        if (ctx.workdir / name).is_file():
            return passed(f"{name} present")
    return failed("no CHANGELOG")


STUB = """\
# Changelog

Notable changes to this project, newest first, by date.

## {today}

- started keeping a changelog
"""


@fix_for("changelog")
def fix(ctx: RepoContext):
    import datetime

    def write(workdir: Path) -> list[Path]:
        target = workdir / "CHANGELOG.md"
        target.write_text(STUB.format(today=datetime.date.today().isoformat()))
        return [target]

    apply_file_fix(
        ctx, "changelog",
        describe="add a CHANGELOG.md stub (newest-first, dated entries)",
        why="a changelog tells users what changed without making them read diffs — "
            "and future-you is a user too",
        write_changes=write,
        commit_message="docs: start a changelog",
    )

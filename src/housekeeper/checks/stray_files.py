"""No stray .md/.txt files piling up at the repo root.

Conventional community files are fine; scratch notes, todo lists, and
one-off writeups accumulate and rot. Deliberate keepers go in
.housekeeping.toml: [stray-files] allow = ["DESIGN.md"].
"""

from __future__ import annotations

from ..context import RepoContext
from ..registry import check, failed, passed

CONVENTIONAL = {
    "readme", "changelog", "changes", "history",
    "license", "licence", "copying", "notice",
    "contributing", "code_of_conduct", "security", "support", "governance",
    "authors", "maintainers", "citation", "codeowners",
    "agents", "claude",
}


@check("stray-files", needs=("clone",))
def stray_files(ctx: RepoContext):
    allow = {name.lower() for name in ctx.config.section("stray-files").get("allow", [])}
    stray = sorted(
        entry.name for entry in ctx.workdir.iterdir()
        if entry.is_file()
        and entry.suffix.lower() in (".md", ".txt")
        and entry.stem.lower() not in CONVENTIONAL
        and entry.name.lower() not in allow
    )
    if stray:
        return failed(f"stray files at root: {', '.join(stray)}",
                      note='delete, move into docs/, or keep deliberately via '
                           '[stray-files] allow = [...] in .housekeeping.toml')
    return passed("no stray .md/.txt at the repo root")

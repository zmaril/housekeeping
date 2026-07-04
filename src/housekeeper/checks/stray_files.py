"""One place for todos, one place for notes, nothing piling up at the root.

LLMs love to leave little .md/.txt files everywhere. The policy (all of it
configurable per repo): conventional community files live at the root, todos
live in ONE file (default todo.txt), notes live in ONE directory (default
notes/), and anything else at the root is a stray. Deliberate keepers go in
.housekeeping.toml: [stray-files] allow = ["ROADMAP.md"]. Different systems
are different; this is the default, not a verdict.
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

TODO_STEMS = {"todo", "todos"}


@check("stray-files", needs=("clone",))
def stray_files(ctx: RepoContext):
    settings = ctx.config.section("stray-files")
    todo_file = settings.get("todos", "todo.txt")
    notes_dir = str(settings.get("notes", "notes/")).rstrip("/")
    allow = {str(name).lower() for name in settings.get("allow", [])}

    strays, extra_todo_piles = [], []
    for entry in ctx.workdir.iterdir():
        if not (entry.is_file() and entry.suffix.lower() in (".md", ".txt")):
            continue
        name = entry.name
        if (name.lower() == todo_file.lower()
                or entry.stem.lower() in CONVENTIONAL
                or name.lower() in allow):
            continue
        if entry.stem.lower() in TODO_STEMS:
            extra_todo_piles.append(name)
        else:
            strays.append(name)

    problems = []
    if extra_todo_piles:
        problems.append(f"second todo pile: {', '.join(sorted(extra_todo_piles))} "
                        f"— the todo file is {todo_file}")
    if strays:
        problems.append(f"stray files at root: {', '.join(sorted(strays))}")
    if problems:
        return failed("; ".join(problems),
                      note=f"notes go in {notes_dir}/, todos in {todo_file}; "
                           "deliberate keepers via [stray-files] allow in .housekeeping.toml")
    return passed("no stray .md/.txt at the repo root")

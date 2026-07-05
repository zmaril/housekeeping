"""TODO / TBD / FIXME / WIP markers belong in the todo file, not scattered around.

A `TODO:` dropped in a comment or a doc is a note nobody tracks — it rots in place,
invisible until someone stumbles on it a year later. The policy: those markers live
in ONE file, the same todo pile `stray-files` points at (default `todo.txt`), where
they can actually be triaged. Anywhere else in the tree, they're flagged.

Marker *form* is matched (`TODO:`, `FIXME(`, a `## TODO` heading) in either case — the
word "todo" used in prose ("the todo file") is deliberately left alone. Only tracked
files are scanned. Deliberate keepers go in `.housekeeping.toml`:
`[stray-todos] ignore = ["tests/", ...]`.

Recommended by default; the powderworks fleet enforces it as required.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from ..context import RepoContext, run
from ..registry import check, failed, passed

# A marker in *tag position* — `TODO:` / `FIXME(` / `wip:` — or a heading that leads
# with the marker (`## TODO`). Case-insensitive. The bare word in prose ("the todo
# file", "a todo pile") has no `:`/`(` and isn't a heading, so it's not matched.
MARKER = re.compile(
    r"\b(?:TODO|TBD|FIXME|WIP)\b\s*[:(]"
    r"|^[ \t]*#{1,6}[ \t]+(?:TODO|TBD|FIXME|WIP)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _ignored(rel: str, ignore: list[str]) -> bool:
    for pat in ignore:
        p = pat.rstrip("/")
        if fnmatch(rel, pat) or fnmatch(rel, p) or fnmatch(rel, f"{p}/*"):
            return True
    return False


def tracked_files(workdir: Path) -> list[str]:
    """Repo-relative paths git tracks — so caches, .venv, and node_modules (all
    untracked/ignored) are never scanned, and neither is .git."""
    proc = run(["git", "ls-files", "-z"], cwd=workdir)
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.split("\0") if p]


@check("stray-todos", needs=("clone",))
def stray_todos(ctx: RepoContext):
    todo_file = str(ctx.config.section("stray-files").get("todos", "todo.txt")).lower()
    ignore = [str(p) for p in ctx.config.section("stray-todos").get("ignore", [])]

    hits: list[str] = []
    total = 0
    for rel in tracked_files(ctx.workdir):
        if rel.lower() == todo_file or _ignored(rel, ignore):
            continue
        try:
            text = (ctx.workdir / rel).read_text()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        n = len(MARKER.findall(text))
        if n:
            total += n
            hits.append(f"{rel} ({n})")

    if hits:
        shown = ", ".join(sorted(hits)[:8])
        more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
        return failed(
            f"{total} TODO/FIXME/TBD/WIP marker(s) outside {todo_file}: {shown}{more}",
            note=f"move them into {todo_file} where they get triaged, or keep "
            "deliberate ones via [stray-todos] ignore in .housekeeping.toml",
        )
    return passed(f"no stray TODO/FIXME/TBD/WIP markers — they live in {todo_file}")

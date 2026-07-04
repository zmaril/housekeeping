"""readme-quality: deterministic quality nudges on top of the README floor.

The `readme` check is the *floor* — title, sections, working links — and its own
docstring hands taste to the tidy-up skill. Two signals sit in between, still fully
deterministic: a README with no runnable example leaves the reader guessing how to
actually use the thing, and a placeholder heading (`## TODO`, `## TBD`) is an
unfinished doc shipped as done. Both are recommended nudges. The subjective call —
does the opening paragraph actually say what this *is* — stays with tidy-up, because
detecting it well needs judgement, not a regex.
"""

from __future__ import annotations

import re

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .readme import find_readme

# A fenced code block — a runnable example or command, not just inline `code`.
CODE_FENCE = re.compile(r"^\s*```", re.M)
# A heading that's still a placeholder: TODO / TBD / FIXME / WIP.
PLACEHOLDER_HEADING = re.compile(r"^#{1,6}\s+.*\b(?:TODO|TBD|FIXME|WIP)\b", re.I | re.M)


@check("readme-quality", needs=("clone",))
def readme_quality(ctx: RepoContext):
    path = find_readme(ctx.workdir)
    if path is None:
        return skipped("no README (the readme check covers its absence)")
    text = path.read_text(errors="replace")

    problems = []
    if not CODE_FENCE.search(text):
        problems.append("no fenced code example / command block")
    placeholders = [m.group(0).strip() for m in PLACEHOLDER_HEADING.finditer(text)]
    if placeholders:
        problems.append("placeholder heading(s): " + ", ".join(placeholders[:3]))

    if problems:
        return failed(
            "; ".join(problems),
            note="recommended quality nudge — the required floor is the `readme` "
            "check; the taste pass is the tidy-up skill",
        )
    return passed(f"{path.name} has a code example and no placeholder headings")

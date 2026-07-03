"""README deterministic floor. Quality/taste is the readme-review skill's job."""

from __future__ import annotations

import re
from pathlib import Path

from ..context import RepoContext
from ..registry import check, failed, passed

MIN_WORDS = 150
INSTALL = re.compile(r"^#{1,6}\s.*(install|getting started|quick\s?start|setup)", re.I | re.M)
USAGE = re.compile(r"^#{1,6}\s.*(usage|use|example|how|docs|documentation)", re.I | re.M)
RELATIVE_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def find_readme(workdir: Path) -> Path | None:
    for entry in sorted(workdir.iterdir()):
        if entry.is_file() and entry.stem.lower() == "readme":
            return entry
    return None


@check("readme", needs=("clone",))
def readme(ctx: RepoContext):
    path = find_readme(ctx.workdir)
    if path is None:
        return failed("no README")
    text = path.read_text(errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]

    problems = []
    if not lines or not lines[0].lstrip().startswith("#"):
        # Allow badge/image headers before the title.
        titled = any(line.lstrip().startswith("# ") for line in lines[:10])
        if not titled:
            problems.append("no title heading in the first 10 lines")
    if len(text.split()) < MIN_WORDS:
        problems.append(f"under {MIN_WORDS} words")
    if not INSTALL.search(text):
        problems.append("no install/getting-started section")
    if not USAGE.search(text):
        problems.append("no usage/docs section")
    if "license" not in text.lower():
        problems.append("no license mention")

    broken = []
    for target in RELATIVE_LINK.findall(text):
        clean = target.split("#")[0]
        if clean and not (ctx.workdir / clean).exists():
            broken.append(target)
    if broken:
        problems.append(f"broken relative links: {', '.join(broken[:5])}")

    if problems:
        return failed("; ".join(problems),
                      note="floor check only — /housekeeping runs the readme-review skill for quality")
    return passed(f"{path.name} passes the floor",
                  note="for the quality pass, run the readme-review skill")

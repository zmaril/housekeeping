"""Straitjacket is wired into CI. Wiring only — findings are straitjacket's own business."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed
from .ci import workflow_files


@check("straitjacket", needs=("clone",))
def straitjacket(ctx: RepoContext):
    files = workflow_files(ctx.workdir)
    if not files:
        return failed("no CI workflows at all — wire straitjacket in once CI exists")
    wired = [p.name for p in files if "straitjacket" in p.read_text().lower()]
    if wired:
        return passed(f"straitjacket runs in: {', '.join(wired)}")
    return failed("no workflow step runs straitjacket")


WORKFLOW = """\
name: straitjacket
on:
  push:
    branches: [main]
  pull_request:

jobs:
  straitjacket:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: curl -fsSL https://raw.githubusercontent.com/zmaril/straitjacket/main/install.sh | sh
      - run: straitjacket
"""


@fix_for("straitjacket")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "straitjacket.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(WORKFLOW)
        return [target]

    apply_file_fix(
        ctx,
        "straitjacket",
        describe="add .github/workflows/straitjacket.yml running straitjacket on push + PR",
        why="runs the slop scanner on every push and PR, so LLM tells get flagged "
        "at review time instead of accumulating in the codebase",
        write_changes=write,
        commit_message="ci: run straitjacket",
    )

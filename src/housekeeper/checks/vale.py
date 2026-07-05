"""vale enforces house prose style from CI. Wiring only — findings are vale's
own business.

Overlaps with `straitjacket` on purpose: straitjacket scans for LLM slop, vale
enforces a chosen style guide and terminology (a StylesPath vocabulary). A repo
can reasonably run both; this check only cares that vale is present and wired.
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed
from .ci import workflow_files


def styles_path(workdir: Path) -> str | None:
    """The StylesPath declared in .vale.ini, or "" if none. vale's format keeps
    global keys above the first [glob] section, so a plain line scan reads them
    where configparser (which demands a section header) can't."""
    ini = workdir / ".vale.ini"
    if not ini.is_file():
        return None
    for line in ini.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break  # into the per-glob sections; StylesPath is global, above them
        key, sep, value = stripped.partition("=")
        if sep and key.strip() == "StylesPath":
            return value.strip()
    return ""


@check("vale", needs=("clone",))
def vale(ctx: RepoContext):
    if not (ctx.workdir / ".vale.ini").is_file():
        return failed("no .vale.ini — prose isn't style-checked")
    styles = styles_path(ctx.workdir)
    if styles and not (ctx.workdir / styles).exists():
        return failed(f".vale.ini sets StylesPath = {styles!r} but it doesn't exist")
    files = workflow_files(ctx.workdir)
    wired = [p.name for p in files if "vale" in p.read_text().lower()]
    if not wired:
        return failed(".vale.ini present but no CI workflow runs vale")
    return passed(f"vale runs in: {', '.join(wired)}")


CONFIG = """\
StylesPath = styles
MinAlertLevel = suggestion

Packages = proselint

[*.md]
BasedOnStyles = Vale, proselint
"""

WORKFLOW = """\
name: vale
on:
  push:
    branches: [main]
  pull_request:

jobs:
  vale:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: errata-ai/vale-action@reviewdog
        with:
          fail_on_error: true
"""


@fix_for("vale")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        changed = []
        ini = workdir / ".vale.ini"
        if not ini.is_file():
            ini.write_text(CONFIG)
            changed.append(ini)
        styles = workdir / "styles"
        if not styles.exists():
            styles.mkdir(parents=True, exist_ok=True)
            keep = styles / ".gitkeep"
            keep.write_text("")
            changed.append(keep)
        workflow = workdir / ".github" / "workflows" / "vale.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(WORKFLOW)
        changed.append(workflow)
        return changed

    apply_file_fix(
        ctx,
        "vale",
        describe="add a .vale.ini + styles/ (if missing) and a workflow running "
        "vale on push + PR",
        why="enforces a consistent prose style and terminology on every push and "
        "PR, so docs stay on-voice instead of drifting per author",
        write_changes=write,
        commit_message="ci: run vale",
    )

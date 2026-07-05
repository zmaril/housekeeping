"""codespell catches common misspellings from CI. Wiring only — findings are
codespell's own business.

The fleet's spell checker, deliberately split from vale: vale's dictionary
spell-check drowns technical docs in false positives (every bit of jargon it
doesn't know), so vale is left to style + terminology. codespell instead flags
only a curated list of *known* misspellings — it can't false-positive on a term
it's never heard of — which is why it stays quiet on jargon while still catching
the real typos (webiste -> website). See notes/design.md.
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed
from .ci import workflow_files


@check("codespell", needs=("clone",))
def codespell(ctx: RepoContext):
    files = workflow_files(ctx.workdir)
    wired = [p.name for p in files if "codespell" in p.read_text().lower()]
    if wired:
        return passed(f"codespell runs in: {', '.join(wired)}")
    return failed("no CI workflow runs codespell — typos slip through")


# Fleet-wide skips (vendored/binary/lockfiles) and the small stable set of known
# false positives; codespell needs no config to run, this just cuts the noise.
CONFIG = """\
[codespell]
skip = ./.git,./node_modules,./.venv,./dist,./build,./.mypy_cache,./.ruff_cache,./.pytest_cache,*.lock,*.svg,*.min.js,*.min.css
ignore-words-list = edn,afterall,unparseable
check-hidden = true
"""

WORKFLOW = """\
name: codespell
on:
  push:
    branches: [main]
  pull_request:

jobs:
  codespell:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: codespell-project/actions-codespell@v2
"""


@fix_for("codespell")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        changed = []
        config = workdir / ".codespellrc"
        if not config.is_file():
            config.write_text(CONFIG)
            changed.append(config)
        workflow = workdir / ".github" / "workflows" / "codespell.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(WORKFLOW)
        changed.append(workflow)
        return changed

    apply_file_fix(
        ctx,
        "codespell",
        describe="add a .codespellrc (if missing) and a workflow running "
        "codespell on push + PR",
        why="catches common misspellings on every push and PR — low-noise by "
        "design (it only knows real typos, not your jargon), so it stays quiet "
        "where a dictionary spell-checker would cry wolf",
        write_changes=write,
        commit_message="ci: run codespell",
    )

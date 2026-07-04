"""Conventional commits: enforced in CI, documented where contributors look.

History is never judged retroactively — the enforcement point is PR titles
plus squash-merge titling, so every commit from adoption onward conforms.
Recent default-branch adherence is reported as a note, not a verdict.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix, confirm, console
from ..registry import check, failed, fix_for, passed
from .ci import workflow_files

ENFORCERS = re.compile(
    r"commitlint|semantic-pull-request|conventional|cocogitto|convco", re.I
)
CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([^)]+\))?!?: .+"
)


def enforced_in_ci(workdir: Path) -> bool:
    return any(
        ENFORCERS.search(path.read_text(errors="replace"))
        for path in workflow_files(workdir)
    )


def documented(workdir: Path) -> bool:
    for name in ("CONTRIBUTING.md", "README.md", "README"):
        path = workdir / name
        if (
            path.is_file()
            and "conventional commit" in path.read_text(errors="replace").lower()
        ):
            return True
    return False


def adherence(ctx: RepoContext) -> str:
    commits = ctx.try_api(f"repos/{ctx.repo}/commits", params={"per_page": 20}) or []
    titles = [c["commit"]["message"].splitlines()[0] for c in commits]
    titles = [t for t in titles if not t.startswith("Merge ")]
    if not titles:
        return ""
    hits = sum(1 for t in titles if CONVENTIONAL.match(t))
    return f"recent {ctx.default_branch} adherence: {hits}/{len(titles)}"


@check("conventional-commits", needs=("clone", "api"))
def conventional_commits(ctx: RepoContext):
    problems = []
    if not enforced_in_ci(ctx.workdir):
        problems.append("no CI enforcement (PR-title check or commitlint)")
    if not documented(ctx.workdir):
        problems.append("not mentioned in README/CONTRIBUTING")
    note = adherence(ctx)
    if problems:
        return failed("; ".join(problems), note)
    return passed("enforced in CI and documented", note)


WORKFLOW = """\
name: conventional
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]

jobs:
  pr-title:
    runs-on: ubuntu-latest
    steps:
      - name: PR title follows conventional commits
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: |
          echo "$TITLE" | grep -qE \\
            '^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\\([a-z0-9./_-]+\\))?!?: .+' || {
            echo "PR title must follow conventional commits: type(scope): summary"
            echo "see https://www.conventionalcommits.org"
            exit 1
          }
"""


@fix_for("conventional-commits")
def fix(ctx: RepoContext):
    info = ctx.repo_info
    if info.get("squash_merge_commit_title") != "PR_TITLE":
        console.print(
            "\nWith squash merges titled from the PR title, enforcing conventional "
            "PR titles makes every future default-branch commit conventional by "
            "construction — no history rewrite, old commits just stay old."
        )
        if confirm(f"Set squash merges on {ctx.repo} to title from the PR title?"):
            ctx.api(
                f"repos/{ctx.repo}",
                method="PATCH",
                input={
                    "squash_merge_commit_title": "PR_TITLE",
                    "squash_merge_commit_message": "PR_BODY",
                },
            )
            console.print("[green]squash merges now title from the PR title[/green]")

    if not enforced_in_ci(ctx.workdir):

        def write(workdir: Path) -> list[Path]:
            target = workdir / ".github" / "workflows" / "conventional.yml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(WORKFLOW)
            return [target]

        apply_file_fix(
            ctx,
            "conventional-commits",
            describe="add .github/workflows/conventional.yml enforcing conventional PR titles",
            why="machine-readable commit titles unlock changelog and release automation "
            "(release-please, semantic-release, conventional-changelog)",
            write_changes=write,
            commit_message="ci: enforce conventional PR titles",
        )
    if not documented(ctx.workdir):
        console.print(
            "[dim]also mention conventional commits in README/CONTRIBUTING — "
            "prose placement is a judgment call, so that part isn't automated[/dim]"
        )

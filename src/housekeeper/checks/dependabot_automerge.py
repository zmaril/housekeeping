"""dependabot-automerge: dependabot PRs auto-merge once required checks pass.

Opt in per repo with `[allow-auto-merge] dependabot = true` in .housekeeping.toml
(which also requires `enabled = true` - GitHub's repo auto-merge setting must be on).
When opted in, the repo needs a workflow that, for dependabot's PRs only, turns on
auto-merge (`gh pr merge --auto`), so GitHub merges them the moment their REQUIRED
checks go green - and never before. This only actually gates on green CI if the repo
has required status checks registered (see the required-checks check); without that,
auto-merge fires as soon as branch protection alone is satisfied. Majors are left for
a human (fetch-metadata scopes the merge to non-major bumps).
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed, skipped
from .ci import workflow_files

WORKFLOW = """\
name: dependabot-automerge
on: pull_request

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    runs-on: ubuntu-latest
    if: github.event.pull_request.user.login == 'dependabot[bot]'
    steps:
      - name: Fetch dependabot metadata
        id: meta
        uses: dependabot/fetch-metadata@v2
      - name: Enable auto-merge for non-major bumps
        if: steps.meta.outputs.update-type != 'version-update:semver-major'
        run: gh pr merge --auto --squash "$PR_URL"
        env:
          PR_URL: ${{ github.event.pull_request.html_url }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
"""


def _has_automerge_workflow(workdir: Path) -> bool:
    """A workflow that, gated to dependabot's actor, enables PR auto-merge.
    Conservative text match - presence/shape, not execution."""
    for path in workflow_files(workdir):
        text = path.read_text(errors="replace")
        gated = "dependabot[bot]" in text
        merges = "gh pr merge --auto" in text or "enablePullRequestAutoMerge" in text
        if gated and merges:
            return True
    return False


@check("dependabot-automerge", needs=("clone",))
def dependabot_automerge(ctx: RepoContext):
    section = ctx.config.section("allow-auto-merge")
    if not bool(section.get("dependabot", False)):
        return skipped(
            "dependabot auto-merge not opted in",
            note="opt in with [allow-auto-merge] dependabot = true "
            "(needs enabled = true too)",
        )
    if not bool(section.get("enabled", False)):
        return failed(
            "[allow-auto-merge] dependabot = true but enabled is false",
            note="GitHub auto-merge must be on (enabled = true) for dependabot "
            "auto-merge to work - see the allow-auto-merge check",
        )
    if not _has_automerge_workflow(ctx.workdir):
        return failed(
            "opted into dependabot auto-merge but no workflow enables it",
            note="run `housekeeper fix dependabot-automerge`; it only gates on green "
            "CI if required-checks is green (checks must be required contexts)",
        )
    return passed(
        "dependabot auto-merge workflow present",
        note="gates on green CI only if required-checks is green",
    )


@fix_for("dependabot-automerge")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "dependabot-automerge.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(WORKFLOW)
        return [target]

    apply_file_fix(
        ctx,
        "dependabot-automerge",
        describe="add .github/workflows/dependabot-automerge.yml "
        "(auto-merge dependabot PRs once required checks pass)",
        why="dependabot opens a steady stream of small dependency PRs; auto-merge "
        "lands the safe ones (non-major, checks green) without a human babysitting "
        "each - and never merges a red or major bump",
        write_changes=write,
        commit_message="ci: auto-merge dependabot PRs when checks pass",
    )

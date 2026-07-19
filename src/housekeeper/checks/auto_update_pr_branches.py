"""auto-update-pr-branches: keep open PR branches current with main after each merge.

Only meaningful when the default branch requires branches be up to date before
merging (`required_status_checks.strict`; the strict-status-checks check). With
strict on, every merge to the default branch leaves the other open PRs behind,
and each one has to be updated by hand with the "Update branch" button before it
can merge in turn. This check asks for a workflow that does that clicking: on a
push to the default branch it updates the head of each selected open PR via the
update-branch API (the same merge-main-into-branch the button performs).

When strict is off there is nothing to keep current, so the check skips; when
strict can't be read (no admin token) it skips and says so. The fix ships the
workflow the same way the dependabot-automerge and straitjacket checks ship
theirs.
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, fix_for
from .ci import workflow_files
from .strict_status_checks import strict_workflow_gate

WORKFLOW = """\
name: auto-update-pr-branches

# Keep open PR branches current with the default branch.
#
# When a repo requires branches to be up to date before merge
# (required_status_checks.strict), every merge to the default branch leaves the
# other open PRs behind, and each one has to be updated by hand with the "Update
# branch" button. This workflow does that clicking: on every push to the default
# branch it merges the default branch into the head of each selected open PR via
# the update-branch API (the same merge-main-into-branch the button performs). A
# true rebase would rewrite the PR's history and fight force-push protections, so
# button-equivalent update is the right default here.
#
# Storm control: N open PRs each get updated on every merge, and each update
# kicks that PR's CI. Two things keep this bounded:
#   1. This workflow triggers only on pushes to the default branch. Updating a PR
#      branch is not a push to the default branch, so it never re-triggers
#      itself; the only fan-out is one CI run per updated PR.
#   2. The selectors below (edit to taste) keep it to PRs that are actually
#      ready, and the concurrency group coalesces a burst of merges into a single
#      pass against the newest default branch.
# For a very busy repo, GitHub's native merge queue is the heavier-duty
# alternative and subsumes this workflow entirely.
#
# Token: the update-branch API needs contents:write and pull-requests:write. The
# built-in GITHUB_TOKEN has both for same-repo branches (the fleet case), so no
# PAT is required. It cannot push to a fork's branch, so PRs from forks are
# skipped and reported rather than failed.

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: auto-update-pr-branches
  cancel-in-progress: true

permissions:
  contents: write
  pull-requests: write

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      # A PR is updated if it matches ANY enabled selector.
      UPDATE_NON_DRAFT: "true"   # any non-draft PR
      UPDATE_AUTO_MERGE: "true"  # PRs with auto-merge enabled (even drafts)
      UPDATE_LABEL: ""           # PRs carrying this label; empty disables it
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            const nonDraft = process.env.UPDATE_NON_DRAFT === "true";
            const autoMerge = process.env.UPDATE_AUTO_MERGE === "true";
            const label = (process.env.UPDATE_LABEL || "").trim();
            const { owner, repo } = context.repo;
            const slug = `${owner}/${repo}`;
            const base = context.payload.repository.default_branch;

            const prs = await github.paginate(github.rest.pulls.list, {
              owner, repo, state: "open", base, per_page: 100,
            });

            const updated = [], conflicted = [], skipped = [], failed = [];

            const mergeState = async (number) => {
              // mergeable_state is computed asynchronously; poll until it settles.
              for (let i = 0; i < 4; i++) {
                const { data } = await github.rest.pulls.get({ owner, repo, pull_number: number });
                if (data.mergeable_state && data.mergeable_state !== "unknown") return data.mergeable_state;
                await new Promise((r) => setTimeout(r, 2000));
              }
              return "unknown";
            };

            for (const pr of prs) {
              const tag = `#${pr.number} ${pr.title}`;
              if (pr.head.repo && pr.head.repo.full_name !== slug) {
                skipped.push(`${tag} (fork; token cannot push)`);
                continue;
              }
              const selected =
                (nonDraft && !pr.draft) ||
                (autoMerge && pr.auto_merge) ||
                (label && pr.labels.some((l) => l.name === label));
              if (!selected) {
                skipped.push(`${tag} (not selected)`);
                continue;
              }

              const state = await mergeState(pr.number);
              if (state === "dirty") {
                conflicted.push(tag);
                continue;
              }
              if (state !== "behind") {
                skipped.push(`${tag} (up to date: ${state})`);
                continue;
              }

              try {
                await github.rest.pulls.updateBranch({ owner, repo, pull_number: pr.number });
                updated.push(tag);
              } catch (e) {
                const msg = (e && e.message) || String(e);
                if (e.status === 422 && /conflict/i.test(msg)) conflicted.push(tag);
                else failed.push(`${tag} (${msg})`);
              }
            }

            const lines = [
              "## Auto-update PR branches",
              "",
              `Base \\`${base}\\`, ${prs.length} open PR(s) scanned`,
              "",
            ];
            const section = (title, items) => {
              lines.push(`### ${title} (${items.length})`);
              lines.push(...(items.length ? items.map((i) => `- ${i}`) : ["_none_"]), "");
            };
            section("Updated", updated);
            section("Conflicts (need a manual merge or rebase)", conflicted);
            section("Skipped", skipped);
            if (failed.length) section("Failed", failed);
            await core.summary.addRaw(lines.join("\\n")).write();

            if (failed.length) core.setFailed(`${failed.length} PR(s) failed to update`);
"""


def _has_workflow(workdir: Path) -> bool:
    """A workflow that updates open PR branches via the update-branch API.
    Conservative text match - presence/shape, not execution."""
    for path in workflow_files(workdir):
        text = path.read_text(errors="replace")
        if "github.rest.pulls.updateBranch" in text or "update-branch" in text:
            return True
    return False


@check("auto-update-pr-branches", needs=("api", "admin", "clone"))
def auto_update_pr_branches(ctx: RepoContext):
    return strict_workflow_gate(
        ctx,
        present=_has_workflow(ctx.workdir),
        absent_details="strict up-to-date is required but nothing keeps open PRs "
        "current with main after each merge",
        absent_note="run `housekeeper fix auto-update-pr-branches`",
        present_details="open PR branches are auto-updated when main moves",
    )


@fix_for("auto-update-pr-branches")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "auto-update-pr-branches.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(WORKFLOW)
        return [target]

    apply_file_fix(
        ctx,
        "auto-update-pr-branches",
        describe="add .github/workflows/auto-update-pr-branches.yml "
        "(update open PR branches when main moves)",
        why="with strict up-to-date required, every merge to main leaves the other "
        "open PRs behind and each has to be updated by hand before it can merge; "
        "this workflow does that clicking on every push to main, so the queue of "
        "open PRs keeps flowing without a human pressing 'Update branch'",
        write_changes=write,
        commit_message="ci: auto-update open PR branches when main moves",
    )

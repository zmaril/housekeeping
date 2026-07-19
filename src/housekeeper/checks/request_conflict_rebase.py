"""request-conflict-rebase: ask an agent to rebase open PRs that truly conflict with main.

The companion auto-update-pr-branches check keeps behind-but-clean PR branches
current by merging the default branch into them. It cannot help a PR whose branch
has a REAL merge conflict with the default branch (`mergeable_state == "dirty"`):
the update-branch API refuses, and the conflict has to be resolved by editing the
branch. That gap is what auto-update-pr-branches can only surface in its
"Conflicts" summary and skip. This check asks for the companion workflow that
closes it: on every push to the default branch it finds the conflicted open PRs
and posts a comment mentioning `@claude` with the resolve context, so the Claude
GitHub app (if installed) rebases them.

Design, sibling not merged: each housekeeper check owns exactly one workflow file
and each fix writes exactly one file; folding this behavior into
auto-update-pr-branches.yml would make two checks and two fixes co-own and
clobber a single file. A separate `on: push` trigger is fine because a
truly-conflicted PR can't be helped by an update-branch pass regardless of
ordering, so the two workflows need not be sequenced; the only cost is one extra
open-PR list call per push, which is negligible.

Gating mirrors auto-update-pr-branches exactly: it only matters when the default
branch requires branches be up to date before merging (`required_status_checks.strict`,
the strict-status-checks check). When strict is off there is nothing to keep
flowing, so it skips; when strict can't be read (no admin token) it skips and says
so. Honest edge: the check verifies the workflow is PRESENT only -- it does not
and cannot verify the Claude GitHub app is installed, without which the comment is
still a useful human-actionable flag on the PR.
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, fix_for
from .ci import workflow_files
from .strict_status_checks import strict_workflow_gate

WORKFLOW = """\
name: request-conflict-rebase

# Ask an agent to rebase open PRs that truly conflict with the default branch.
#
# The companion auto-update-pr-branches workflow keeps behind-but-clean PR
# branches current by merging the default branch into them. It cannot help a PR
# whose branch has a REAL merge conflict with the default branch
# (mergeable_state "dirty") -- the update-branch API refuses, and the conflict
# has to be resolved by editing the branch. This workflow closes that gap: on
# every push to the default branch it finds the conflicted open PRs and posts a
# comment mentioning @claude with the context needed to resolve them, so the
# Claude GitHub app (if installed) picks it up and does the rebase.
#
# Dependency, stated honestly: this only causes a rebase to happen if the repo
# has the Claude GitHub app installed and configured to act on @claude mentions.
# Without it, the comment is still a useful, human-actionable flag on the PR. The
# housekeeper check verifies this workflow is PRESENT; it does not and cannot
# verify the app is installed.
#
# Dedupe: a hidden marker (HTML comment) identifies an open request. A conflicted
# PR that already carries one is skipped, so a burst of merges does not re-comment
# every push -- one comment per conflict episode. When a PR stops being conflicted
# its open request is edited to a resolved note, re-arming a fresh request if it
# conflicts again.
#
# Token: posting a PR comment needs pull-requests:write; the built-in GITHUB_TOKEN
# has it for same-repo PRs. Fork PRs are skipped (the resolving agent could not
# push to a fork branch) and surfaced in the job summary.

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: request-conflict-rebase
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write

jobs:
  request:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      MARKER: "<!-- housekeeping:request-conflict-rebase -->"
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            const marker = process.env.MARKER;
            const { owner, repo } = context.repo;
            const base = context.payload.repository.default_branch;
            const slug = `${owner}/${repo}`;

            const openPrs = await github.paginate(github.rest.pulls.list, {
              owner, repo, base, state: "open", per_page: 100,
            });

            // Verdict buckets, keyed so the summary can walk them in a fixed order.
            const report = { requested: [], already: [], cleared: [], skipped: [] };

            // mergeable_state is computed asynchronously; poll pulls.get until it
            // settles, then hand back the whole PR (or null if it never settles).
            async function settledPr(number) {
              for (let attempt = 0; attempt < 5; attempt++) {
                const got = await github.rest.pulls.get({ owner, repo, pull_number: number });
                if (got.data.mergeable_state && got.data.mergeable_state !== "unknown") {
                  return got.data;
                }
                await new Promise((resolve) => setTimeout(resolve, 2000));
              }
              return null;
            }

            // The open rebase request on a PR (identified by the hidden marker),
            // or undefined when none has been posted yet.
            async function openRequest(number) {
              const posted = await github.paginate(github.rest.issues.listComments, {
                owner, repo, issue_number: number, per_page: 100,
              });
              return posted.find((comment) => (comment.body || "").includes(marker));
            }

            for (const pr of openPrs) {
              const tag = `#${pr.number} ${pr.title}`;
              const fromFork = pr.head.repo && pr.head.repo.full_name !== slug;
              if (fromFork) {
                report.skipped.push(`${tag} (fork; agent cannot push to its branch)`);
                continue;
              }

              const pull = await settledPr(pr.number);
              const existing = await openRequest(pr.number);
              const conflicts = Boolean(pull) && pull.mergeable_state === "dirty";

              if (conflicts && existing) {
                report.already.push(tag);
              } else if (conflicts) {
                const body = [
                  marker,
                  `@claude this PR conflicts with \\`${base}\\` and cannot merge until the conflict is resolved.`,
                  "",
                  `Please merge \\`${base}\\` into \\`${pr.head.ref}\\` and resolve the conflicts:`,
                  `- Base: \\`${base}\\``,
                  `- Branch: \\`${pr.head.ref}\\``,
                  "- Resolve conflicts against the base branch; where a change is additive, keep both sides.",
                  "- Re-verify the PR's checks pass after resolving.",
                ].join("\\n");
                await github.rest.issues.createComment({ owner, repo, issue_number: pr.number, body });
                report.requested.push(tag);
              } else if (existing) {
                await github.rest.issues.updateComment({
                  owner, repo, comment_id: existing.id,
                  body: `${marker}\\n_Conflict with \\`${base}\\` resolved; rebase request cleared._`,
                });
                report.cleared.push(tag);
              }
            }

            // Job summary: one section per bucket, in declared order.
            const headings = [
              ["requested", "Rebase requested"],
              ["already", "Already requested"],
              ["cleared", "Cleared (now mergeable)"],
              ["skipped", "Skipped"],
            ];
            const out = [
              "## Request conflict rebase",
              "",
              `Base \\`${base}\\`, ${openPrs.length} open PR(s) scanned`,
              "",
            ];
            for (const [key, heading] of headings) {
              const items = report[key];
              out.push(`### ${heading} (${items.length})`);
              out.push(...(items.length ? items.map((item) => `- ${item}`) : ["_none_"]));
              out.push("");
            }
            await core.summary.addRaw(out.join("\\n")).write();
"""


def _has_workflow(workdir: Path) -> bool:
    """A workflow that requests an @claude rebase for PRs conflicting with main.
    Conservative text match - presence/shape, not execution."""
    for path in workflow_files(workdir):
        text = path.read_text(errors="replace")
        if "housekeeping:request-conflict-rebase" in text:
            return True
    return False


@check("request-conflict-rebase", needs=("api", "admin", "clone"))
def request_conflict_rebase(ctx: RepoContext):
    return strict_workflow_gate(
        ctx,
        present=_has_workflow(ctx.workdir),
        absent_details="strict up-to-date is required but nothing asks for a "
        "rebase of open PRs that truly conflict with main",
        absent_note="run `housekeeper fix request-conflict-rebase`",
        present_details="open PRs that conflict with main get an @claude rebase "
        "request (companion to auto-update-pr-branches; verifies the workflow's "
        "presence, not that the Claude GitHub app is installed)",
    )


@fix_for("request-conflict-rebase")
def fix(ctx: RepoContext):
    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "request-conflict-rebase.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(WORKFLOW)
        return [target]

    apply_file_fix(
        ctx,
        "request-conflict-rebase",
        describe="add .github/workflows/request-conflict-rebase.yml "
        "(ask @claude to rebase PRs that conflict with main)",
        why="the companion auto-update-pr-branches workflow keeps behind-but-clean "
        "PR branches current, but it can't help a PR whose branch truly conflicts "
        "with main -- the update-branch API refuses and the conflict has to be "
        "resolved by editing the branch; this workflow posts an @claude comment on "
        "each conflicted open PR with the resolve context, so the Claude GitHub app "
        "(if installed) rebases it instead of the PR sitting flagged until a human "
        "notices",
        write_changes=write,
        commit_message="ci: request @claude rebase for PRs that conflict with main",
    )

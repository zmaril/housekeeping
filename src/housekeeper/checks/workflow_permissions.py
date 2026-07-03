"""Default GITHUB_TOKEN for workflows is read-only."""

from __future__ import annotations

from ..context import GhError, RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped


@check("workflow-permissions", needs=("api",))
def workflow_permissions(ctx: RepoContext):
    try:
        perms = ctx.api(f"repos/{ctx.repo}/actions/permissions/workflow")
    except GhError as e:
        if e.status == 403:
            return skipped("workflow permissions not visible to this token",
                           note="run housekeeper locally (or pass an admin-read token) for coverage")
        raise
    problems = []
    if perms.get("default_workflow_permissions") != "read":
        problems.append("default GITHUB_TOKEN is read-write")
    if perms.get("can_approve_pull_request_reviews"):
        problems.append("workflows can approve PRs")
    if problems:
        return failed("; ".join(problems),
                      note="jobs that need more can declare `permissions:` explicitly")
    return passed("workflow GITHUB_TOKEN is read-only, cannot approve PRs")


@fix_for("workflow-permissions")
def fix(ctx: RepoContext):
    console.print(
        "\nEvery workflow gets a GITHUB_TOKEN; with the read-write default, any "
        "compromised action in your CI can push code or tags. Read-only is least "
        "privilege — a job that needs more declares it in its own `permissions:` block."
    )
    if not confirm(f"Set default workflow permissions on {ctx.repo} to read-only?"):
        console.print("Nothing done.")
        return
    ctx.api(f"repos/{ctx.repo}/actions/permissions/workflow", method="PUT", input={
        "default_workflow_permissions": "read",
        "can_approve_pull_request_reviews": False,
    })
    console.print("[green]workflow token set to read-only[/green]")

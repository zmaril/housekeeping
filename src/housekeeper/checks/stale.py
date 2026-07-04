"""No PRs idle >30 days; no merged-but-undeleted branches; merges clean up
after themselves (delete_branch_on_merge)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..context import RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed

IDLE_DAYS = 30
MAX_BRANCHES = 20


def merged_branches(ctx: RepoContext) -> tuple[list[str], int]:
    branches = ctx.api(f"repos/{ctx.repo}/branches", params={"per_page": 100})
    others = [b["name"] for b in branches if b["name"] != ctx.default_branch]
    merged = []
    for name in others[:MAX_BRANCHES]:
        compare = ctx.try_api(f"repos/{ctx.repo}/compare/{ctx.default_branch}...{name}")
        if compare and compare.get("ahead_by") == 0:
            merged.append(name)
    return merged, len(others)


@check("stale", needs=("api",))
def stale(ctx: RepoContext):
    problems, notes = [], []

    cutoff = datetime.now(timezone.utc) - timedelta(days=IDLE_DAYS)
    prs = ctx.api(f"repos/{ctx.repo}/pulls", params={"state": "open", "per_page": 100})
    idle = [
        p
        for p in prs
        if datetime.fromisoformat(p["updated_at"].replace("Z", "+00:00")) < cutoff
    ]
    if idle:
        numbers = ", ".join(f"#{p['number']}" for p in idle[:5])
        problems.append(f"{len(idle)} PR(s) idle >{IDLE_DAYS}d ({numbers})")

    merged, total_others = merged_branches(ctx)
    if merged:
        problems.append(
            f"{len(merged)} merged branch(es) not deleted: {', '.join(merged[:5])}"
        )
    if total_others > MAX_BRANCHES:
        notes.append(f"only first {MAX_BRANCHES} of {total_others} branches examined")

    auto_delete = ctx.repo_info.get("delete_branch_on_merge")
    if auto_delete is False:
        problems.append(
            "merged branches aren't auto-deleted (delete_branch_on_merge off)"
        )
    elif auto_delete is None:
        notes.append("auto-delete-on-merge setting not visible to this token")

    note = "; ".join(notes)
    if problems:
        return failed("; ".join(problems), note)
    return passed(
        f"{len(prs)} open PR(s), none idle; no merged branches lingering; "
        "merges auto-delete their branch",
        note,
    )


@fix_for("stale")
def fix(ctx: RepoContext):
    if ctx.repo_info.get("delete_branch_on_merge") is False:
        console.print(
            "\nWith delete_branch_on_merge off, every web-UI merge leaves its branch "
            "behind — the pile you're looking at. On, merged branches clean up "
            "themselves (and restore is one click on the PR if ever needed)."
        )
        if confirm(f"Enable auto-delete of merged branches on {ctx.repo}?"):
            ctx.api(
                f"repos/{ctx.repo}",
                method="PATCH",
                input={"delete_branch_on_merge": True},
            )
            console.print("[green]delete_branch_on_merge enabled[/green]")

    merged, _ = merged_branches(ctx)
    if merged:
        console.print(
            f"\nMerged into {ctx.default_branch}, safe to delete "
            f"(commits are already on {ctx.default_branch}): {', '.join(merged)}"
        )
        if confirm(f"Delete {len(merged)} merged branch(es)?"):
            for name in merged:
                ctx.api(f"repos/{ctx.repo}/git/refs/heads/{name}", method="DELETE")
                console.print(f"[green]deleted {name}[/green]")

    # Idle PRs need a human decision — close, revive, or merge. Not automated.

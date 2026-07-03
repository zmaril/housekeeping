"""No PRs idle >30 days; no merged-but-undeleted branches. Report only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..context import RepoContext
from ..registry import check, failed, passed

IDLE_DAYS = 30
MAX_BRANCHES = 20


@check("stale", needs=("api",))
def stale(ctx: RepoContext):
    problems = []

    cutoff = datetime.now(timezone.utc) - timedelta(days=IDLE_DAYS)
    prs = ctx.api(f"repos/{ctx.repo}/pulls", params={"state": "open", "per_page": 100})
    idle = [p for p in prs
            if datetime.fromisoformat(p["updated_at"].replace("Z", "+00:00")) < cutoff]
    if idle:
        numbers = ", ".join(f"#{p['number']}" for p in idle[:5])
        problems.append(f"{len(idle)} PR(s) idle >{IDLE_DAYS}d ({numbers})")

    branches = ctx.api(f"repos/{ctx.repo}/branches", params={"per_page": 100})
    others = [b["name"] for b in branches if b["name"] != ctx.default_branch]
    merged = []
    for name in others[:MAX_BRANCHES]:
        compare = ctx.try_api(f"repos/{ctx.repo}/compare/{ctx.default_branch}...{name}")
        if compare and compare.get("ahead_by") == 0:
            merged.append(name)
    if merged:
        problems.append(f"{len(merged)} merged branch(es) not deleted: {', '.join(merged[:5])}")
    note = f"only first {MAX_BRANCHES} of {len(others)} branches examined" \
        if len(others) > MAX_BRANCHES else ""

    if problems:
        return failed("; ".join(problems), note)
    return passed(f"{len(prs)} open PR(s), none idle; no merged branches lingering", note)

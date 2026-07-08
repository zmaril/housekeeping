"""ruleset-bypass: a gating ruleset must name a bypass actor.

GitHub rulesets — unlike classic branch protection — ignore
`gh pr merge --admin` unless the actor appears in the ruleset's
`bypass_actors`. With an empty bypass list, every legitimate emergency
(the bootstrap PR that can't self-approve, the fix for the very red it's
gated on) becomes settings surgery: disable the ruleset, merge, re-enable.
The escape hatch the fleet standardizes on is Repository admin with
`bypass_mode: always` — protection stays active for everyone else, and the
override is one flag instead of an API session.
"""

from __future__ import annotations

from ..context import RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped

ADMIN_BYPASS = {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}

# Rule types that gate merging — a ruleset carrying one of these can deadlock
# a PR, so it's the kind that needs an escape hatch.
GATING = {"pull_request", "required_status_checks"}


def gating_rulesets(ctx: RepoContext) -> list[dict] | None:
    """Active branch rulesets that gate merges, with full detail (the list
    endpoint omits rules and bypass_actors). None when not visible."""
    rulesets = ctx.try_api(f"repos/{ctx.repo}/rulesets", none_on=(403, 404))
    if rulesets is None:
        return None
    out = []
    for r in rulesets:
        if r.get("target") != "branch" or r.get("enforcement") != "active":
            continue
        detail = ctx.try_api(f"repos/{ctx.repo}/rulesets/{r['id']}", none_on=(403, 404))
        if not detail:
            continue
        if GATING & {rule.get("type") for rule in detail.get("rules", [])}:
            out.append(detail)
    return out


@check("ruleset-bypass", needs=("api", "admin"))
def ruleset_bypass(ctx: RepoContext):
    gating = gating_rulesets(ctx)
    if gating is None:
        return skipped(
            "rulesets not visible to this token",
            note="run housekeeper locally (or pass an admin-read token) for coverage",
        )
    if not gating:
        return skipped(
            "no active gating rulesets",
            note="classic branch protection honors --admin natively",
        )
    naked = [
        d.get("name", f"id {d.get('id')}") for d in gating if not d.get("bypass_actors")
    ]
    if naked:
        return failed(
            f"gating ruleset(s) with no bypass actor: {', '.join(naked)} "
            "(housekeeper fix ruleset-bypass)",
            note="rulesets ignore `gh pr merge --admin` without a bypass actor — "
            "grant Repository admin (bypass_mode: always) so an emergency is a "
            "flag, not settings surgery",
        )
    names = ", ".join(d.get("name", "?") for d in gating)
    return passed(f"every gating ruleset has a bypass actor: {names}")


@fix_for("ruleset-bypass")
def fix(ctx: RepoContext):
    for detail in gating_rulesets(ctx) or []:
        if detail.get("bypass_actors"):
            continue
        name = detail.get("name", f"id {detail.get('id')}")
        if not confirm(f"grant Repository admin bypass on ruleset {name!r}?"):
            continue
        # PUT wants the writable ruleset shape back, not the GET envelope.
        body = {
            k: v
            for k, v in detail.items()
            if k in ("name", "target", "enforcement", "conditions", "rules")
        }
        body["bypass_actors"] = [ADMIN_BYPASS]
        ctx.api(f"repos/{ctx.repo}/rulesets/{detail['id']}", method="PUT", input=body)
        console.print(
            f"[green]ruleset {name!r}: Repository admin bypass granted[/green]"
        )

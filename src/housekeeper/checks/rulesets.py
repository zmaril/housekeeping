"""Shared helpers for the API fixes that edit the default-branch ruleset."""

from __future__ import annotations

from ..context import RepoContext


def default_branch_ruleset(ctx: RepoContext) -> dict | None:
    """The active ruleset targeting the default branch, fully expanded, or None."""
    for summary in ctx.api(f"repos/{ctx.repo}/rulesets") or []:
        full = ctx.api(f"repos/{ctx.repo}/rulesets/{summary['id']}")
        include = ((full.get("conditions") or {}).get("ref_name") or {}).get(
            "include"
        ) or []
        if full.get("enforcement") == "active" and "~DEFAULT_BRANCH" in include:
            return full
    return None


def put_ruleset(ctx: RepoContext, ruleset: dict, rules: list[dict]) -> None:
    """PUT `ruleset` back with `rules`, keeping its identity and conditions."""
    ctx.api(
        f"repos/{ctx.repo}/rulesets/{ruleset['id']}",
        method="PUT",
        input={
            "name": ruleset["name"],
            "target": ruleset.get("target", "branch"),
            "enforcement": "active",
            "conditions": ruleset["conditions"],
            "rules": rules,
        },
    )

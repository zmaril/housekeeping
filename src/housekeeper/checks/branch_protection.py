"""Default branch must be protected: PRs required, no force-push, no deletion."""

from __future__ import annotations

from ..context import RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped

WANTED = {
    "pull_request": "pull requests required",
    "non_fast_forward": "force-pushes blocked",
    "deletion": "branch deletion blocked",
}


def effective_rules(ctx: RepoContext) -> set[str] | None:
    """Rule types active on the default branch (rulesets, incl. org-level)."""
    rules = ctx.try_api(f"repos/{ctx.repo}/rules/branches/{ctx.default_branch}",
                        none_on=(403, 404))
    if rules is None:
        return None
    return {r["type"] for r in rules}


def classic_rules(ctx: RepoContext) -> set[str] | None:
    prot = ctx.try_api(f"repos/{ctx.repo}/branches/{ctx.default_branch}/protection",
                       none_on=(403, 404))
    if prot is None:
        return None
    rules = set()
    if prot.get("required_pull_request_reviews"):
        rules.add("pull_request")
    if not prot.get("allow_force_pushes", {}).get("enabled", False):
        rules.add("non_fast_forward")
    if not prot.get("allow_deletions", {}).get("enabled", False):
        rules.add("deletion")
    if prot.get("required_status_checks", {}).get("contexts"):
        rules.add("required_status_checks")
    return rules


@check("branch-protection", needs=("api", "admin"))
def branch_protection(ctx: RepoContext):
    rules = effective_rules(ctx)
    classic = classic_rules(ctx)
    if rules is None and classic is None and ctx.visibility == "private":
        return skipped("branch protection not available",
                       note="private repos need a paid plan for rulesets/protection")
    active = (rules or set()) | (classic or set())

    missing = [label for rule, label in WANTED.items() if rule not in active]
    if missing:
        return failed(f"{ctx.default_branch} missing: {', '.join(missing)}")

    note = ""
    if "required_status_checks" not in active:
        note = "no required status checks — add them once CI is green"
    return passed(f"{ctx.default_branch} protected: {', '.join(WANTED.values())}", note)


@fix_for("branch-protection")
def fix(ctx: RepoContext):
    console.print(
        f"\nThis fix will create a ruleset on [cyan]{ctx.repo}[/cyan] protecting "
        f"[cyan]{ctx.default_branch}[/cyan]: PRs required (0 approvals — solo-maintainer "
        f"friendly), force-pushes blocked, deletion blocked."
    )
    console.print(
        "[dim]Why: with protection on, changes land through PRs where CI can gate them, "
        "published history can't be rewritten under people who pulled it, and the branch "
        "can't be deleted by a fat-fingered push.[/dim]"
    )
    console.print("[dim]Required status checks are not set here — add them once CI exists and is green.[/dim]")
    if not confirm("Apply the ruleset?"):
        console.print("Nothing done.")
        return
    ruleset = {
        "name": "housekeeping: protect default branch",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
        ],
    }
    ctx.api(f"repos/{ctx.repo}/rulesets", method="POST", input=ruleset)
    console.print("[green]Ruleset created.[/green]")

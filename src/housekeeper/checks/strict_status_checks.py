"""strict-status-checks: the default branch must require branches be up to date before merging.

Two PRs can each be green on their own base yet break `main` together — a semantic
merge conflict from a stale base. GitHub's `required_status_checks.strict` closes that
hole: with it on, a PR can only merge once its branch is up to date with the base, so CI
reruns against the *true merged state* rather than a stale snapshot. That's the "Require
branches to be up to date before merging" checkbox in branch protection.

This check reads that flag from both rulesets and classic protection (OR-ing, like
required-checks), and additionally recommends the repo-level "Always suggest updating
pull request branches" setting (`allow_update_branch`) — a soft nudge that keeps PR
branches current, not a hard gate.

Note: for a high-PR-volume repo a merge queue is the stronger tool — strict can serialize
merges (every merge invalidates the others' up-to-date status), whereas a queue batches
and tests them together. Strict is the right floor; a queue is the scale-up.
"""

from __future__ import annotations

from ..context import GhError, RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped
from .rulesets import default_branch_ruleset, put_ruleset


def strict_flag(ctx: RepoContext) -> tuple[bool, bool, bool]:
    """(found, strict, both_unreadable) from ruleset + classic protection, OR-ing strict.

    `found` is True once any required-status-checks config is read from either source;
    `both_unreadable` is True when both reads folded to None (403/404).
    """
    rules = ctx.try_api(
        f"repos/{ctx.repo}/rules/branches/{ctx.default_branch}", none_on=(403, 404)
    )
    classic = ctx.try_api(
        f"repos/{ctx.repo}/branches/{ctx.default_branch}"
        "/protection/required_status_checks",
        none_on=(403, 404),
    )
    found = False
    strict = False
    for rule in rules or []:
        if rule.get("type") == "required_status_checks":
            found = True
            params = rule.get("parameters") or {}
            strict = strict or bool(params.get("strict_required_status_checks_policy"))
    if isinstance(classic, dict):
        found = True
        strict = strict or bool(classic.get("strict"))
    return found, strict, rules is None and classic is None


def strict_workflow_gate(
    ctx: RepoContext,
    present: bool,
    absent_details: str,
    absent_note: str,
    present_details: str,
):
    """Shared verdict for a check that wants a workflow only when the default
    branch requires branches be up to date before merge.

    Reads strict via `strict_flag` and applies the gating both the
    auto-update-pr-branches and request-conflict-rebase checks share: skip (with
    the standard reasons) when protection is unreadable or strict is off, fail
    with the caller's `absent_*` message when strict is on but `present` is False,
    else pass with `present_details`. Centralizing it keeps the two sibling checks
    from each carrying — and drifting — a copy of the same branching.
    """
    _found, strict, both_unreadable = strict_flag(ctx)
    if both_unreadable:
        return skipped(
            "couldn't read branch protection to tell whether strict up-to-date "
            "is required",
            note="needs an admin token to read the ruleset / classic protection",
        )
    if not strict:
        return skipped(
            "main doesn't require branches to be up to date before merge",
            note="only needed when required_status_checks.strict is on; see the "
            "strict-status-checks check",
        )
    if not present:
        return failed(absent_details, note=absent_note)
    return passed(present_details)


@check("strict-status-checks", needs=("api", "admin"))
def strict_status_checks(ctx: RepoContext):
    found, strict, both_unreadable = strict_flag(ctx)
    if not found:
        if both_unreadable and ctx.visibility == "private":
            return skipped(
                "can't read branch protection",
                note="private repos need a paid plan for rulesets/protection, "
                "or run with an admin token",
            )
        return failed(
            f"{ctx.default_branch} does not require branches to be up to date before "
            "merging (no required status checks configured)",
            note="enable required status checks then strict; see the required-checks check",
        )
    aub = ctx.repo_info.get("allow_update_branch")
    if strict:
        details = (
            f"{ctx.default_branch} requires branches be up to date before merging "
            "(required_status_checks.strict=true)"
        )
        if not aub:
            return passed(
                details,
                note="also enable 'Always suggest updating pull request branches' "
                "(allow_update_branch) so contributors keep PR branches current",
            )
        return passed(details)
    stale = (
        f"{ctx.default_branch} allows merging stale branches "
        "(required_status_checks.strict is false)"
    )
    if not aub:
        stale += (
            "; 'Always suggest updating pull request branches' (allow_update_branch) "
            "is also off"
        )
    return failed(
        stale,
        note="turn on 'Require branches to be up to date before merging' so CI tests "
        "the true merged state",
    )


@fix_for("strict-status-checks")
def fix(ctx: RepoContext):
    ruleset = default_branch_ruleset(ctx)
    if ruleset is None:
        console.print(
            "[yellow]no active default-branch ruleset — run the branch-protection fix "
            "first, then this one[/yellow]"
        )
        return
    has_rsc = any(r.get("type") == "required_status_checks" for r in ruleset["rules"])
    if not has_rsc:
        console.print(
            "[yellow]no required status checks on the default branch — run the "
            "required-checks fix first, then this one[/yellow]"
        )
        return
    console.print(
        f"\nThis will require branches be up to date before merging on "
        f"[cyan]{ctx.default_branch}[/cyan] and turn on 'Always suggest updating pull "
        f"request branches'."
    )
    console.print(
        "[dim]Why: with strict on, a PR can only merge once its branch is current, so CI "
        "reruns against the true merged state — two individually-green PRs from stale "
        "bases can't silently break main.[/dim]"
    )
    if not confirm("Require up-to-date branches?"):
        console.print("Nothing done.")
        return
    # Keep every rule; flip strict on the required_status_checks one. Rules read from a
    # ruleset object are already the type+parameters shape PUT accepts.
    rules = []
    for r in ruleset["rules"]:
        entry: dict = {"type": r["type"]}
        if r.get("parameters"):
            params = dict(r["parameters"])
            if r["type"] == "required_status_checks":
                params["strict_required_status_checks_policy"] = True
            entry["parameters"] = params
        rules.append(entry)
    try:
        put_ruleset(ctx, ruleset, rules)
        ctx.api(
            f"repos/{ctx.repo}",
            method="PATCH",
            input={"allow_update_branch": True},
        )
    except GhError as e:
        if e.status == 403:
            console.print(
                "[red]token lacks admin (HTTP 403)[/red] — re-run with an admin token, "
                "or flip it by hand in repo Settings -> Branches (ruleset) and Settings "
                "-> General -> Pull Requests."
            )
            return
        raise
    console.print(
        "[green]Strict status checks enabled; 'always suggest updating PR branches' "
        "turned on.[/green]"
    )

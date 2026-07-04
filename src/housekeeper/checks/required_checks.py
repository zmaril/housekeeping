"""required-checks: the default branch must REQUIRE the repo's PR status checks.

Branch protection can require PRs yet require no *status checks* — then a red CI run
doesn't block the merge button and the gate is theatre. Strict means every check that
runs on a PR (test, lint, build, straitjacket, …) is a required status check, so a PR is
all-green or it can't land. Fan-out helper jobs (a paths-filter `changes` job, which
carries `outputs:`) aren't graded — they pass data, not verdicts.
"""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped
from .ci import parse_workflow, triggers, workflow_files


def required_contexts(ctx: RepoContext) -> tuple[bool, set[str]]:
    """(is anything required?, the required status-check contexts) from ruleset + classic."""
    configured = False
    contexts: set[str] = set()
    rules = ctx.try_api(
        f"repos/{ctx.repo}/rules/branches/{ctx.default_branch}", none_on=(403, 404)
    )
    for rule in rules or []:
        if rule.get("type") == "required_status_checks":
            configured = True
            params = rule.get("parameters") or {}
            for c in params.get("required_status_checks", []):
                if c.get("context"):
                    contexts.add(c["context"])
    classic = ctx.try_api(
        f"repos/{ctx.repo}/branches/{ctx.default_branch}"
        "/protection/required_status_checks/contexts",
        none_on=(403, 404),
    )
    if isinstance(classic, list):
        configured = True
        contexts |= {c for c in classic if c}
    return configured, contexts


def pr_check_jobs(workdir: Path) -> set[str]:
    """Check-run names the repo's OWN workflows post on a PR — a job's `name:` (else its
    id). Skips fan-out helpers (jobs with `outputs:`) and dynamic/matrix names."""
    names: set[str] = set()
    for path in workflow_files(workdir):
        workflow = parse_workflow(path)
        if not workflow or "pull_request" not in triggers(workflow):
            continue
        for job_id, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict) or job.get("outputs"):
                continue
            name = job.get("name") or job_id
            if isinstance(name, str) and "${{" not in name:
                names.add(name)
    return names


@check("required-checks", needs=("clone", "api"))
def required_checks(ctx: RepoContext):
    jobs = pr_check_jobs(ctx.workdir)
    if not jobs:
        return skipped(
            "no PR status checks to require",
            note="no workflow posts a check on pull_request (ci-exists covers that)",
        )
    configured, required = required_contexts(ctx)
    if not configured:
        if ctx.visibility == "private":
            return skipped(
                "can't read required checks",
                note="private repos need a paid plan for rulesets/protection",
            )
        return failed(
            f"{ctx.default_branch} requires no status checks — a red run doesn't block "
            f"the merge; require: {', '.join(sorted(jobs))}"
        )
    missing = sorted(jobs - required)
    if missing:
        return failed(
            f"run on PRs but aren't required on {ctx.default_branch}: {', '.join(missing)}"
        )
    return passed(
        f"{ctx.default_branch} requires all {len(jobs)} PR check(s): "
        f"{', '.join(sorted(jobs))}"
    )


def _default_branch_ruleset(ctx: RepoContext) -> dict | None:
    for summary in ctx.api(f"repos/{ctx.repo}/rulesets") or []:
        full = ctx.api(f"repos/{ctx.repo}/rulesets/{summary['id']}")
        include = ((full.get("conditions") or {}).get("ref_name") or {}).get(
            "include"
        ) or []
        if full.get("enforcement") == "active" and "~DEFAULT_BRANCH" in include:
            return full
    return None


@fix_for("required-checks")
def fix(ctx: RepoContext):
    jobs = sorted(pr_check_jobs(ctx.workdir))
    if not jobs:
        console.print("[yellow]no PR checks to require[/yellow]")
        return
    ruleset = _default_branch_ruleset(ctx)
    if ruleset is None:
        console.print(
            "[yellow]no active default-branch ruleset — run the branch-protection fix "
            "first, then this one[/yellow]"
        )
        return
    console.print(
        f"\nThis will require these status checks on [cyan]{ctx.default_branch}[/cyan]: "
        f"{', '.join(jobs)}"
    )
    console.print(
        "[dim]Why: with them required, a red check blocks the merge button — the PR is "
        "all-green or it doesn't land. Skipped (path-scoped) jobs count as green.[/dim]"
    )
    if not confirm("Require these checks?"):
        console.print("Nothing done.")
        return
    # Keep every other rule; strip GitHub's read-only envelope down to what PUT accepts.
    rules = [
        {
            "type": r["type"],
            **({"parameters": r["parameters"]} if r.get("parameters") else {}),
        }
        for r in ruleset["rules"]
        if r.get("type") != "required_status_checks"
    ]
    rules.append(
        {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [{"context": c} for c in jobs],
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
            },
        }
    )
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
    console.print("[green]Required status checks set.[/green]")

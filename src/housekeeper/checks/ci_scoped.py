"""ci-scoped: heavy CI jobs shouldn't run on every PR regardless of what changed.

A job that apt-installs system libraries or runs a native compiler (cargo, go, docker,
xcode) costs minutes; running it on a docs-only PR is waste — and once checks are
*required*, waste you can't merge past. "Scoped" means the job is gated to the files that
could affect it: a workflow-level `paths:` filter, a job `if:`, or a `needs:` on a
fan-out (paths-filter) job. Light steps (`bun install`, a JS bundle) aren't graded — the
signal is system-package installs and native builds, which are unambiguously heavy.
"""

from __future__ import annotations

import re

from ..context import RepoContext
from ..registry import check, failed, passed
from .ci import parse_workflow, triggers, workflow_files

HEAVY = re.compile(
    r"\bapt-get install\b|\bapt install\b"
    r"|\bcargo (?:build|check|test|clippy|nextest)\b"
    r"|\bgo build\b|\bdocker build\b|\bxcodebuild\b|\bgradlew?\b|\bmsbuild\b"
    r"|\bcmake --build\b",
    re.I,
)


def pr_paths_filtered(workflow: dict) -> bool:
    on = workflow.get("on", workflow.get(True, {}))
    if isinstance(on, dict):
        pr = on.get("pull_request")
        if isinstance(pr, dict) and (pr.get("paths") or pr.get("paths-ignore")):
            return True
    return False


def job_steps_text(job: dict) -> str:
    chunks = []
    for step in job.get("steps") or []:
        if isinstance(step, dict):
            for key in ("run", "uses", "name"):
                if isinstance(step.get(key), str):
                    chunks.append(step[key])
    return "\n".join(chunks)


def fanout_jobs(workflow: dict) -> set[str]:
    """Job ids that fan out data (carry `outputs:`) — a `needs:` on one is scoping."""
    return {
        jid
        for jid, job in (workflow.get("jobs") or {}).items()
        if isinstance(job, dict) and job.get("outputs")
    }


@check("ci-scoped", needs=("clone",))
def ci_scoped(ctx: RepoContext):
    unscoped = []
    for path in workflow_files(ctx.workdir):
        workflow = parse_workflow(path)
        if not workflow or "pull_request" not in triggers(workflow):
            continue
        if pr_paths_filtered(workflow):
            continue  # the whole workflow is already path-scoped
        fanout = fanout_jobs(workflow)
        for jid, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict) or job.get("outputs"):
                continue
            if not HEAVY.search(job_steps_text(job)):
                continue
            needs = job.get("needs")
            needs = [needs] if isinstance(needs, str) else (needs or [])
            scoped = bool(job.get("if")) or any(n in fanout for n in needs)
            if not scoped:
                unscoped.append(f"{path.name}:{job.get('name') or jid}")
    if unscoped:
        return failed(
            "heavy jobs run on every PR unscoped: " + ", ".join(sorted(unscoped)),
            note="gate them on a paths-filter `changes` job (job-level `if:`), so a "
            "docs-only PR skips the compile/install — a skipped required check still "
            "counts as green",
        )
    return passed("no heavy CI job runs unscoped on every PR")

"""ci-job-timeout: CI jobs should set timeout-minutes, so a hung job can't run for
hours.

GitHub's default job timeout is 6 hours. A wedged network call, a deadlocked test,
a process waiting on input that never comes — with no `timeout-minutes` it sits
there burning runner minutes and showing a lying "in progress" until the ceiling,
and on a required check it blocks the merge the whole time. A modest
`timeout-minutes` turns an infinite hang into a bounded, obvious failure.

Checked on jobs in push/PR workflows (the ones a contributor waits on). Jobs that
just call a reusable workflow (`uses:` at the job level) can't set the key and are
skipped. Recommended.
"""

from __future__ import annotations

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .ci import triggers, workflow_files, workflows

CI_EVENTS = {"push", "pull_request"}


@check("ci-job-timeout", needs=("clone",))
def ci_job_timeout(ctx: RepoContext):
    if not workflow_files(ctx.workdir):
        return skipped("no workflows (ci-exists covers the absence of CI)")
    unbounded: list[str] = []
    for path, wf in workflows(ctx.workdir):
        if not (CI_EVENTS & triggers(wf)):
            continue
        for jid, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict) or "uses" in job:
                continue  # reusable-workflow calls can't set timeout-minutes
            if job.get("timeout-minutes") is None:
                unbounded.append(f"{path.name}: {job.get('name') or jid}")
    if unbounded:
        return failed(
            "CI jobs without timeout-minutes: " + ", ".join(unbounded),
            note="set a `timeout-minutes:` on each job so a hung run fails fast "
            "instead of burning the 6-hour default",
        )
    return passed("every push/PR CI job bounds its runtime with timeout-minutes")

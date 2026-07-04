"""ci-scheduled-run: CI should run on a schedule, not only on push/PR.

Push-only CI never exercises the repo between commits. Bitrot — an expiring token,
a dependency that moved, a pinned action that got yanked, a flaky test that only
shows up under load — sits invisible until someone happens to push, and then it's
tangled up with their change. A `schedule:` trigger runs the suite on a quiet repo
so the breakage surfaces on its own, before it's anyone's problem to debug.

Recommended: not every repo needs it, and a repo with no workflows at all is
ci-exists's problem, not this one.
"""

from __future__ import annotations

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .ci import triggers, workflow_files, workflows


@check("ci-scheduled-run", needs=("clone",))
def ci_scheduled_run(ctx: RepoContext):
    if not workflow_files(ctx.workdir):
        return skipped("no workflows (ci-exists covers the absence of CI)")
    scheduled = [
        path.name for path, wf in workflows(ctx.workdir) if "schedule" in triggers(wf)
    ]
    if scheduled:
        return passed(f"scheduled run configured: {', '.join(sorted(scheduled))}")
    return failed(
        "no workflow runs on a schedule",
        note="add a `schedule:` (cron) trigger to a workflow so bitrot surfaces on a "
        "quiet repo instead of on the next contributor's PR",
    )

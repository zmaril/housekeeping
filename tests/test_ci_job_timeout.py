from conftest import Ctx, write_wf

from housekeeper.checks.ci_job_timeout import ci_job_timeout
from housekeeper.registry import Status


def test_flags_job_without_timeout(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\n"
        "jobs:\n  test:\n    steps: [{run: pytest}]\n",
    )
    r = ci_job_timeout(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "test" in r.details


def test_passes_when_all_jobs_bounded(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\n"
        "jobs:\n  test:\n    timeout-minutes: 10\n    steps: [{run: pytest}]\n",
    )
    assert ci_job_timeout(Ctx(tmp_path)).status == Status.PASS


def test_reusable_workflow_call_is_skipped(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\n"
        "jobs:\n  call:\n    uses: ./.github/workflows/reusable.yml\n",
    )
    assert ci_job_timeout(Ctx(tmp_path)).status == Status.PASS


def test_non_ci_workflow_jobs_ignored(tmp_path):
    # A schedule-only maintenance workflow isn't the push/PR path a contributor waits on.
    write_wf(
        tmp_path,
        "cron.yml",
        "name: Cron\non: {schedule: [{cron: '0 0 * * *'}]}\n"
        "jobs:\n  sweep:\n    steps: [{run: cleanup}]\n",
    )
    assert ci_job_timeout(Ctx(tmp_path)).status == Status.PASS


def test_skips_when_no_workflows(tmp_path):
    assert ci_job_timeout(Ctx(tmp_path)).status == Status.SKIP

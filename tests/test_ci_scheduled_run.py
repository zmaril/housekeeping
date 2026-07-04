from conftest import Ctx, write_wf

from housekeeper.checks.ci_scheduled_run import ci_scheduled_run
from housekeeper.registry import Status


def test_passes_with_schedule_trigger(tmp_path):
    write_wf(
        tmp_path,
        "nightly.yml",
        "name: N\non: {schedule: [{cron: '0 7 * * 1'}]}\n"
        "jobs: {t: {steps: [{run: pytest}]}}\n",
    )
    assert ci_scheduled_run(Ctx(tmp_path)).status == Status.PASS


def test_fails_when_only_push_pr(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {push: {}, pull_request: {}}\n"
        "jobs: {t: {steps: [{run: pytest}]}}\n",
    )
    assert ci_scheduled_run(Ctx(tmp_path)).status == Status.FAIL


def test_skips_when_no_workflows(tmp_path):
    assert ci_scheduled_run(Ctx(tmp_path)).status == Status.SKIP

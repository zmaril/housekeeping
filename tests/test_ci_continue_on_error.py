from conftest import Ctx, write_wf

from housekeeper.checks.ci_continue_on_error import ci_continue_on_error
from housekeeper.registry import Status


def test_flags_test_step_that_masks_failure(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        """\
name: CI
on: {pull_request: {}}
jobs:
  test:
    steps:
      - name: run tests
        run: cargo test
        continue-on-error: true
""",
    )
    r = ci_continue_on_error(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "run tests" in r.details


def test_flags_whole_job_marked_continue_on_error(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        """\
name: CI
on: {pull_request: {}}
jobs:
  lint:
    name: Lint
    continue-on-error: true
    steps: [{run: ruff check .}]
""",
    )
    r = ci_continue_on_error(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "job 'Lint'" in r.details


def test_does_not_flag_tolerant_non_gating_step(tmp_path):
    # An optional coverage upload allowed to fail isn't a test/lint/build step.
    write_wf(
        tmp_path,
        "ci.yml",
        """\
name: CI
on: {pull_request: {}}
jobs:
  test:
    steps:
      - {run: cargo test}
      - name: upload coverage
        uses: codecov/codecov-action@v4
        continue-on-error: true
""",
    )
    assert ci_continue_on_error(Ctx(tmp_path)).status == Status.PASS


def test_clean_workflow_passes(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\njobs: {test: {steps: [{run: pytest}]}}\n",
    )
    assert ci_continue_on_error(Ctx(tmp_path)).status == Status.PASS

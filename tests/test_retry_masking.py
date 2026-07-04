from conftest import Ctx, write_wf

from housekeeper.checks.retry_masking import retry_masking
from housekeeper.registry import Status


def test_flags_reruns_in_workflow_command(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\n"
        "jobs:\n  test:\n    steps: [{run: pytest --reruns 3}]\n",
    )
    r = retry_masking(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "ci.yml" in r.details


def test_flags_pytest_rerun_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "--reruns 2"\n'
    )
    r = retry_masking(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "pyproject.toml" in r.details


def test_flags_playwright_nonzero_retries(tmp_path):
    (tmp_path / "playwright.config.ts").write_text(
        "export default defineConfig({ retries: 2 });\n"
    )
    assert retry_masking(Ctx(tmp_path)).status == Status.FAIL


def test_passes_with_no_retries(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\njobs: {test: {steps: [{run: pytest}]}}\n",
    )
    (tmp_path / "playwright.config.ts").write_text(
        "export default defineConfig({ retries: 0 });\n"
    )
    assert retry_masking(Ctx(tmp_path)).status == Status.PASS

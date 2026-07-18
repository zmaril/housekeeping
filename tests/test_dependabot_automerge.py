from types import SimpleNamespace

from housekeeper.checks.dependabot_automerge import (
    WORKFLOW,
    _has_automerge_workflow,
    dependabot_automerge,
)
from housekeeper.config import Config
from housekeeper.registry import Status

from conftest import write_wf


def ctx(tmp_path, overrides=None):
    return SimpleNamespace(workdir=tmp_path, config=Config(overrides or {}))


def test_not_opted_in_skips(tmp_path):
    result = dependabot_automerge(ctx(tmp_path))
    assert result.status == Status.SKIP


def test_opted_in_without_enabled_fails(tmp_path):
    result = dependabot_automerge(
        ctx(tmp_path, {"allow-auto-merge": {"dependabot": True}})
    )
    assert result.status == Status.FAIL
    assert "enabled" in result.details


def test_opted_in_no_workflow_fails(tmp_path):
    result = dependabot_automerge(
        ctx(tmp_path, {"allow-auto-merge": {"dependabot": True, "enabled": True}})
    )
    assert result.status == Status.FAIL
    assert "no workflow" in result.details and "enables it" in result.details


def test_opted_in_with_workflow_passes(tmp_path):
    write_wf(tmp_path, "dependabot-automerge.yml", WORKFLOW)
    result = dependabot_automerge(
        ctx(tmp_path, {"allow-auto-merge": {"dependabot": True, "enabled": True}})
    )
    assert result.status == Status.PASS


def test_wrong_shape_workflow_fails(tmp_path):
    # gated to dependabot's actor, but never enables auto-merge.
    write_wf(
        tmp_path,
        "dependabot-automerge.yml",
        "name: x\non: pull_request\njobs:\n  j:\n    runs-on: ubuntu-latest\n"
        "    if: github.event.pull_request.user.login == 'dependabot[bot]'\n"
        "    steps:\n      - run: echo hi\n",
    )
    result = dependabot_automerge(
        ctx(tmp_path, {"allow-auto-merge": {"dependabot": True, "enabled": True}})
    )
    assert result.status == Status.FAIL
    assert "no workflow" in result.details


def test_shipped_workflow_satisfies_detector(tmp_path):
    write_wf(tmp_path, "dependabot-automerge.yml", WORKFLOW)
    assert _has_automerge_workflow(tmp_path)
    assert "dependabot[bot]" in WORKFLOW
    assert "gh pr merge --auto" in WORKFLOW

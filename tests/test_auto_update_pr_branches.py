from pathlib import Path
from types import SimpleNamespace

import yaml

import housekeeper.checks.auto_update_pr_branches as mod
from housekeeper.checks.auto_update_pr_branches import (
    WORKFLOW,
    _has_workflow,
    auto_update_pr_branches,
    fix,
)
from housekeeper.registry import Status

from conftest import write_wf


class FakeCtx:
    """Feeds strict_flag a branch-protection read and the check a workdir.

    `strict` None models the no-admin case: both protection reads fold to None,
    which strict_flag reports as unreadable. True/False returns a ruleset rule
    carrying that strict policy.
    """

    repo, default_branch = "o/r", "main"

    def __init__(self, tmp_path, strict=None):
        self.workdir = tmp_path
        self._strict = strict

    def try_api(self, path, none_on=(404,), **kw):
        if self._strict is None or "/rules/branches/" not in path:
            return None
        params = {"strict_required_status_checks_policy": self._strict}
        return [{"type": "required_status_checks", "parameters": params}]


def test_strict_on_with_workflow_passes(tmp_path):
    write_wf(tmp_path, "auto-update-pr-branches.yml", WORKFLOW)
    result = auto_update_pr_branches(FakeCtx(tmp_path, strict=True))
    assert result.status == Status.PASS
    assert "auto-updated" in result.details


def test_strict_on_without_workflow_fails(tmp_path):
    result = auto_update_pr_branches(FakeCtx(tmp_path, strict=True))
    assert result.status == Status.FAIL
    assert "keeps open PRs current" in result.details
    assert "housekeeper fix auto-update-pr-branches" in result.note


def test_strict_off_skips(tmp_path):
    result = auto_update_pr_branches(FakeCtx(tmp_path, strict=False))
    assert result.status == Status.SKIP
    assert "up to date before merge" in result.details
    assert "strict-status-checks" in result.note


def test_strict_unreadable_skips(tmp_path):
    # strict=None: both protection reads fold to None (no admin token), so skip.
    result = auto_update_pr_branches(FakeCtx(tmp_path))
    assert result.status == Status.SKIP
    assert "couldn't read branch protection" in result.details
    assert "admin" in result.note


def test_workflow_parses_and_has_expected_shape():
    data = yaml.safe_load(WORKFLOW)
    # YAML 1.1 parses bare `on` as the boolean True, like the CI checks expect.
    on = data.get("on", data.get(True))
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"]["branches"] == ["main"]
    assert data["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert data["concurrency"]["group"] == "auto-update-pr-branches"
    assert data["concurrency"]["cancel-in-progress"] is True
    assert data["jobs"]["update"]["timeout-minutes"] == 15


def test_detector_matches_shipped_workflow(tmp_path):
    write_wf(tmp_path, "auto-update-pr-branches.yml", WORKFLOW)
    assert _has_workflow(tmp_path)
    assert "github.rest.pulls.updateBranch" in WORKFLOW


def test_fix_writes_the_workflow(tmp_path, monkeypatch):
    written: list[Path] = []

    def fake_apply(ctx, name, describe, why, write_changes, commit_message):
        assert name == "auto-update-pr-branches"
        assert commit_message == "ci: auto-update open PR branches when main moves"
        written.extend(write_changes(tmp_path))

    monkeypatch.setattr(mod, "apply_file_fix", fake_apply)
    fix(SimpleNamespace())
    assert written == [
        tmp_path / ".github" / "workflows" / "auto-update-pr-branches.yml"
    ]
    text = written[0].read_text()
    assert text == WORKFLOW
    assert "github.rest.pulls.updateBranch" in text


def test_scaffold_includes_the_workflow():
    from housekeeper.scaffold import build_files

    files = build_files("demo", "python", private=False, dependabot_automerge=False)
    path = ".github/workflows/auto-update-pr-branches.yml"
    assert path in files
    assert files[path] == WORKFLOW
    assert "github.rest.pulls.updateBranch" in files[path]

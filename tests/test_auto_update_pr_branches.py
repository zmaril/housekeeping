from pathlib import Path
from types import SimpleNamespace

import housekeeper.checks.auto_update_pr_branches as mod
from housekeeper.checks.auto_update_pr_branches import (
    WORKFLOW,
    _has_workflow,
    auto_update_pr_branches,
    fix,
)
from housekeeper.registry import Status

from conftest import StrictCtx, load_workflow, write_wf

# The strict-gating branches (skip/fail/pass) live on the shared helper and are
# covered in test_strict_workflow_gate.py; here we cover this check's own wiring.


def test_strict_on_with_workflow_passes(tmp_path):
    write_wf(tmp_path, "auto-update-pr-branches.yml", WORKFLOW)
    result = auto_update_pr_branches(StrictCtx(tmp_path, strict=True))
    assert result.status == Status.PASS
    assert "auto-updated" in result.details


def test_strict_on_without_workflow_fails(tmp_path):
    result = auto_update_pr_branches(StrictCtx(tmp_path, strict=True))
    assert result.status == Status.FAIL
    assert "keeps open PRs current" in result.details
    assert "housekeeper fix auto-update-pr-branches" in result.note


def test_workflow_parses_and_has_expected_shape():
    data, on = load_workflow(WORKFLOW)
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

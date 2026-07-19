from pathlib import Path
from types import SimpleNamespace

import housekeeper.checks.request_conflict_rebase as mod
from housekeeper.checks.request_conflict_rebase import (
    WORKFLOW,
    _has_workflow,
    fix,
    request_conflict_rebase,
)
from housekeeper.registry import Status

from conftest import StrictCtx, load_workflow, write_wf

# The strict-gating branches (skip/fail/pass) are covered against the shared
# helper in test_strict_workflow_gate.py; here we cover this check's own wiring:
# its verdict messages, the shipped workflow's shape, the detector, the fix, the
# scaffold, and the self-adopted copy's byte-identity.


def test_present_workflow_passes_with_claude_message(tmp_path):
    write_wf(tmp_path, "request-conflict-rebase.yml", WORKFLOW)
    result = request_conflict_rebase(StrictCtx(tmp_path, strict=True))
    assert result.status == Status.PASS
    assert "@claude rebase request" in result.details


def test_absent_workflow_fails_pointing_at_the_fix(tmp_path):
    result = request_conflict_rebase(StrictCtx(tmp_path, strict=True))
    assert result.status == Status.FAIL
    assert "truly conflict with main" in result.details
    assert "housekeeper fix request-conflict-rebase" in result.note


def test_workflow_parses_and_has_expected_shape():
    data, on = load_workflow(WORKFLOW)
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"]["branches"] == ["main"]
    # Posting a comment needs only pull-requests:write; no contents:write here.
    assert data["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert data["concurrency"]["group"] == "request-conflict-rebase"
    assert data["concurrency"]["cancel-in-progress"] is True
    assert data["jobs"]["request"]["timeout-minutes"] == 15


def test_detector_matches_shipped_workflow(tmp_path):
    write_wf(tmp_path, "request-conflict-rebase.yml", WORKFLOW)
    assert _has_workflow(tmp_path)
    # The marker the detector keys on appears verbatim in the workflow.
    assert "housekeeping:request-conflict-rebase" in WORKFLOW


def test_check_recognizes_a_customized_mention_handle(tmp_path):
    # A repo that points MENTION_HANDLE at a different bot must still be
    # recognized and pass: recognition keys on the marker, never the handle.
    customized = WORKFLOW.replace(
        'MENTION_HANDLE: "claude"', 'MENTION_HANDLE: "rebase-bot"'
    )
    assert customized != WORKFLOW
    write_wf(tmp_path, "request-conflict-rebase.yml", customized)
    assert _has_workflow(tmp_path)
    result = request_conflict_rebase(StrictCtx(tmp_path, strict=True))
    assert result.status == Status.PASS


def test_detector_keys_on_marker_not_the_handle(tmp_path):
    # Marker present, the literal "claude"/"@claude" absent entirely: still
    # recognized, proving the matcher is coupled to the marker, not the mention.
    only_marker = (
        "name: x\n"
        "jobs:\n  request:\n    env:\n"
        '      MARKER: "<!-- housekeeping:request-conflict-rebase -->"\n'
        '      MENTION_HANDLE: "rebase-bot"\n'
    )
    assert "claude" not in only_marker
    write_wf(tmp_path, "custom.yml", only_marker)
    assert _has_workflow(tmp_path)


def test_default_mention_handle_is_claude_and_configurable():
    # Ships defaulting to `claude`, resolved with a leading-@ strip so both
    # `claude` and `@claude` work, and rendered into the body via a template.
    assert 'MENTION_HANDLE: "claude"' in WORKFLOW
    assert '(process.env.MENTION_HANDLE || "claude")' in WORKFLOW
    assert 'replace(/^@/, "")' in WORKFLOW
    assert "`@${mention} this PR conflicts" in WORKFLOW


def test_fix_writes_the_workflow(tmp_path, monkeypatch):
    written: list[Path] = []

    def fake_apply(ctx, name, describe, why, write_changes, commit_message):
        assert name == "request-conflict-rebase"
        assert (
            commit_message
            == "ci: request @claude rebase for PRs that conflict with main"
        )
        written.extend(write_changes(tmp_path))

    monkeypatch.setattr(mod, "apply_file_fix", fake_apply)
    fix(SimpleNamespace())
    assert written == [
        tmp_path / ".github" / "workflows" / "request-conflict-rebase.yml"
    ]
    text = written[0].read_text()
    assert text == WORKFLOW
    assert "housekeeping:request-conflict-rebase" in text


def test_scaffold_includes_the_workflow():
    from housekeeper.scaffold import build_files

    files = build_files("demo", "python", private=False, dependabot_automerge=False)
    path = ".github/workflows/request-conflict-rebase.yml"
    assert path in files
    assert files[path] == WORKFLOW
    assert "housekeeping:request-conflict-rebase" in files[path]


def test_self_adopted_copy_is_byte_identical():
    # housekeeping dogfoods its own check: the workflow it ships in its own repo
    # must equal the WORKFLOW constant byte-for-byte (same invariant the scaffold
    # and fix uphold), so the check it dogfoods keeps passing.
    repo_root = Path(__file__).resolve().parents[1]
    committed = repo_root / ".github" / "workflows" / "request-conflict-rebase.yml"
    assert committed.read_text() == WORKFLOW

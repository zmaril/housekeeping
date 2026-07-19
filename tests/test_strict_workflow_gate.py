"""The gating shared by the strict-gated workflow checks, tested once here.

auto-update-pr-branches and request-conflict-rebase both route their verdict
through strict_workflow_gate, so the skip/fail/pass branching is exercised here
rather than duplicated in each check's own test module (the conftest philosophy:
grade the shared thing once).
"""

from housekeeper.checks.strict_status_checks import strict_workflow_gate
from housekeeper.registry import Status

from conftest import StrictCtx

ABSENT = "the workflow is missing"
ABSENT_NOTE = "run the fix"
PRESENT = "the workflow is here"


def _gate(ctx, present):
    return strict_workflow_gate(
        ctx,
        present=present,
        absent_details=ABSENT,
        absent_note=ABSENT_NOTE,
        present_details=PRESENT,
    )


def test_unreadable_protection_skips(tmp_path):
    # strict=None: both protection reads fold to None (no admin token), so skip.
    result = _gate(StrictCtx(tmp_path), present=True)
    assert result.status == Status.SKIP
    assert "couldn't read branch protection" in result.details
    assert "admin" in result.note


def test_strict_off_skips(tmp_path):
    result = _gate(StrictCtx(tmp_path, strict=False), present=True)
    assert result.status == Status.SKIP
    assert "up to date before merge" in result.details
    assert "strict-status-checks" in result.note


def test_strict_on_but_absent_fails_with_caller_message(tmp_path):
    result = _gate(StrictCtx(tmp_path, strict=True), present=False)
    assert result.status == Status.FAIL
    assert result.details == ABSENT
    assert result.note == ABSENT_NOTE


def test_strict_on_and_present_passes_with_caller_message(tmp_path):
    result = _gate(StrictCtx(tmp_path, strict=True), present=True)
    assert result.status == Status.PASS
    assert result.details == PRESENT

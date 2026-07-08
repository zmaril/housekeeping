"""PR-context grading: main-state checks inform on pull_request runs, gate
everywhere else. The third instance of ci-green's self-reference disease
(after the hosting workflow and the housekeeping family) — a required PR
check that grades main deadlocks the very PR carrying the fix."""

from housekeeper.cli import MAIN_STATE_CHECKS, effective_severity


def test_main_state_checks_soften_on_pr_events():
    for name in MAIN_STATE_CHECKS:
        assert effective_severity(name, "required", "pull_request") == (
            "recommended",
            True,
        )


def test_everything_else_keeps_its_severity_on_pr_events():
    assert effective_severity("license", "required", "pull_request") == (
        "required",
        False,
    )
    assert effective_severity("readme", "required", "pull_request") == (
        "required",
        False,
    )


def test_main_state_checks_stay_hard_off_pr_events():
    for event in ("push", "schedule", "workflow_dispatch", ""):
        assert effective_severity("ci-green", "required", event) == ("required", False)


def test_already_soft_severities_pass_through_undemoted():
    # a repo that opted a main-state check down (or off upstream) isn't
    # double-labeled as demoted
    assert effective_severity("ci-green", "recommended", "pull_request") == (
        "recommended",
        False,
    )


def test_the_set_is_exactly_the_pr_immutable_rows():
    # grades of main's runs or repo settings — nothing a PR's diff can change
    assert MAIN_STATE_CHECKS == {"ci-green", "branch-protection", "required-checks"}

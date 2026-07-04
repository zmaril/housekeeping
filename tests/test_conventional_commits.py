from types import SimpleNamespace

from housekeeper.checks.conventional_commits import CONVENTIONAL, conventional_commits
from housekeeper.registry import Status

ENFORCING_WORKFLOW = "name: conventional\non:\n  pull_request:\njobs: {}\n"


def repo(tmp_path, workflow=None, contributing=None):
    if workflow:
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True, exist_ok=True)
        (workflows / "conventional.yml").write_text(workflow)
    if contributing:
        (tmp_path / "CONTRIBUTING.md").write_text(contributing)
    return SimpleNamespace(
        workdir=tmp_path,
        repo="o/r",
        default_branch="main",
        try_api=lambda path, **kw: [
            {"commit": {"message": "feat: a thing"}},
            {"commit": {"message": "update stuff"}},
            {"commit": {"message": "Merge pull request #1 from x"}},
        ],
    )


def test_missing_both_fails_with_adherence_note(tmp_path):
    result = conventional_commits(repo(tmp_path))
    assert result.status == Status.FAIL
    assert (
        "CI enforcement" in result.details and "README/CONTRIBUTING" in result.details
    )
    assert "adherence: 1/2" in result.note  # merge commit excluded


def test_enforced_and_documented_passes(tmp_path):
    ctx = repo(
        tmp_path,
        workflow=ENFORCING_WORKFLOW,
        contributing="We use Conventional Commits for PR titles.",
    )
    assert conventional_commits(ctx).status == Status.PASS


def test_pattern_accepts_and_rejects():
    good = (
        "feat: add thing",
        "fix(cli): handle empty",
        "chore!: drop py310",
        "refactor(checks/ci): split",
    )
    bad = ("Add thing", "feat:missing space", "wip: stuff", "feat(): empty scope ok?")
    for title in good:
        assert CONVENTIONAL.match(title), title
    for title in bad[:3]:
        assert not CONVENTIONAL.match(title), title

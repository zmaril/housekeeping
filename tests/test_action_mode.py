"""Behavior when running as a GitHub Action: limited tokens, self-hosted workflow."""


from housekeeper.checks.ci import ci_green
from housekeeper.checks.dependabot import dependabot
from housekeeper.checks.secret_scanning import secret_scanning
from housekeeper.checks.workflow_permissions import workflow_permissions
from housekeeper.cli import render_markdown
from housekeeper.context import GhError
from housekeeper.registry import Status


class ForbiddenApiCtx:
    """A ctx whose API always 403s, like a plain workflow token on admin reads."""

    repo = "o/r"
    visibility = "public"
    repo_info = {}  # security_and_analysis absent without admin read

    def __init__(self, workdir=None, ecosystems=()):
        self.workdir = workdir
        self.ecosystems = list(ecosystems)

    def api(self, path, **kwargs):
        raise GhError(403, "Resource not accessible by integration")


def test_secret_scanning_skips_without_admin_read():
    result = secret_scanning(ForbiddenApiCtx())
    assert result.status == Status.SKIP
    assert "token" in result.details


def test_workflow_permissions_skips_on_403():
    result = workflow_permissions(ForbiddenApiCtx())
    assert result.status == Status.SKIP


def test_dependabot_unknown_settings_pass_with_note(tmp_path):
    github = tmp_path / ".github"
    github.mkdir()
    (github / "dependabot.yml").write_text(
        'version: 2\nupdates:\n  - package-ecosystem: "cargo"\n'
        '    directory: "/"\n    schedule: {interval: "weekly"}\n'
    )
    from housekeeper.context import Ecosystem

    ctx = ForbiddenApiCtx(workdir=tmp_path,
                          ecosystems=[Ecosystem("cargo", "Cargo.toml", "Cargo.lock", "cargo")])
    result = dependabot(ctx)
    assert result.status == Status.PASS
    assert "not visible to this token" in result.note


def test_dependabot_missing_file_still_fails_with_403s(tmp_path):
    ctx = ForbiddenApiCtx(workdir=tmp_path, ecosystems=[])
    result = dependabot(ctx)
    assert result.status == Status.FAIL
    assert "no .github/dependabot.yml" in result.details


def test_ci_green_excludes_the_hosting_workflow(monkeypatch):
    from test_ci_green import FakeCtx as WorkflowsCtx

    monkeypatch.setenv("GITHUB_WORKFLOW", "housekeeping")
    ctx = WorkflowsCtx(
        [
            {"id": 1, "name": "ci", "path": ".github/workflows/ci.yml", "state": "active"},
            {"id": 2, "name": "housekeeping", "path": ".github/workflows/housekeeping.yml",
             "state": "active"},
        ],
        {1: {"conclusion": "success"}, 2: {"conclusion": "failure"}},  # would deadlock itself
    )
    result = ci_green(ctx)
    assert result.status == Status.PASS
    assert "not grading 'housekeeping'" in result.note


def test_ci_green_grades_housekeeping_workflow_when_outside(monkeypatch):
    from test_ci_green import FakeCtx as WorkflowsCtx

    monkeypatch.delenv("GITHUB_WORKFLOW", raising=False)
    ctx = WorkflowsCtx(
        [{"id": 2, "name": "housekeeping", "path": ".github/workflows/housekeeping.yml",
          "state": "active"}],
        {2: {"conclusion": "failure", "html_url": "u"}},
    )
    assert ci_green(ctx).status == Status.FAIL


def test_render_markdown_escapes_pipes():
    payload = {
        "repo": "o/r", "visibility": "public", "checked_at": "now",
        "results": [{"check": "readme", "status": "fail", "severity": "required",
                     "details": "bad | table", "note": "", "fixable": False}],
    }
    markdown = render_markdown(payload)
    assert "bad \\| table" in markdown
    assert "✗ fail" in markdown

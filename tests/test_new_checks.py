from types import SimpleNamespace

from housekeeper.checks.gitignore import gitignore
from housekeeper.checks.secret_scanning import secret_scanning
from housekeeper.checks.workflow_permissions import workflow_permissions
from housekeeper.context import Ecosystem
from housekeeper.registry import Status


class ApiCtx:
    repo = "o/r"

    def __init__(self, repo_info=None, api_responses=None, visibility="public"):
        self.repo_info = repo_info or {}
        self.visibility = visibility
        self._responses = api_responses or {}

    def api(self, path, **kwargs):
        return self._responses[path]


def security(scanning, push):
    return {
        "security_and_analysis": {
            "secret_scanning": {"status": scanning},
            "secret_scanning_push_protection": {"status": push},
        }
    }


def test_secret_scanning_pass():
    ctx = ApiCtx(repo_info=security("enabled", "enabled"))
    assert secret_scanning(ctx).status == Status.PASS


def test_secret_scanning_flags_each_toggle():
    result = secret_scanning(ApiCtx(repo_info=security("enabled", "disabled")))
    assert result.status == Status.FAIL
    assert "push protection" in result.details


def test_secret_scanning_private_without_ghas_skips():
    ctx = ApiCtx(repo_info={}, visibility="private")
    assert secret_scanning(ctx).status == Status.SKIP


def test_workflow_permissions_pass_and_fail():
    path = "repos/o/r/actions/permissions/workflow"
    good = ApiCtx(
        api_responses={
            path: {
                "default_workflow_permissions": "read",
                "can_approve_pull_request_reviews": False,
            }
        }
    )
    assert workflow_permissions(good).status == Status.PASS

    bad = ApiCtx(
        api_responses={
            path: {
                "default_workflow_permissions": "write",
                "can_approve_pull_request_reviews": True,
            }
        }
    )
    result = workflow_permissions(bad)
    assert result.status == Status.FAIL
    assert "read-write" in result.details and "approve" in result.details


def cargo_ctx(tmp_path):
    return SimpleNamespace(
        workdir=tmp_path,
        ecosystems=[Ecosystem("cargo", "Cargo.toml", "Cargo.lock", "cargo")],
    )


def test_gitignore_missing_file_fails(tmp_path):
    assert gitignore(cargo_ctx(tmp_path)).status == Status.FAIL


def test_gitignore_missing_pattern_fails(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n")
    result = gitignore(cargo_ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "target/" in result.details


def test_gitignore_covered_passes(tmp_path):
    (tmp_path / ".gitignore").write_text("/target\n")  # leading-slash variant counts
    assert gitignore(cargo_ctx(tmp_path)).status == Status.PASS


def test_gitignore_no_known_junk_skips(tmp_path):
    ctx = SimpleNamespace(
        workdir=tmp_path, ecosystems=[Ecosystem("go", "go.mod", "go.sum", "gomod")]
    )
    assert gitignore(ctx).status == Status.SKIP

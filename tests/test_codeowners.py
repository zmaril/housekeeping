from housekeeper.checks.codeowners import codeowners
from housekeeper.registry import Status


class Ctx:
    def __init__(self, tmp_path):
        self.workdir = tmp_path


def test_fails_when_absent(tmp_path):
    assert codeowners(Ctx(tmp_path)).status == Status.FAIL


def test_passes_with_a_rule_in_github_dir(tmp_path):
    d = tmp_path / ".github"
    d.mkdir()
    (d / "CODEOWNERS").write_text("# owners\n* @zmaril\n")
    assert codeowners(Ctx(tmp_path)).status == Status.PASS


def test_passes_with_root_codeowners(tmp_path):
    (tmp_path / "CODEOWNERS").write_text("*.rs @rustlead\n")
    assert codeowners(Ctx(tmp_path)).status == Status.PASS


def test_fails_when_only_comments(tmp_path):
    (tmp_path / "CODEOWNERS").write_text("# TODO: add owners\n\n")
    r = codeowners(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "no ownership rules" in r.details

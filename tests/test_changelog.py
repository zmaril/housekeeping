from types import SimpleNamespace

from housekeeper.checks.changelog import changelog
from housekeeper.registry import Status


def test_missing_changelog_fails(tmp_path):
    assert changelog(SimpleNamespace(workdir=tmp_path)).status == Status.FAIL


def test_changelog_variants_pass(tmp_path):
    (tmp_path / "HISTORY.md").write_text("## 1.0\n- things\n")
    result = changelog(SimpleNamespace(workdir=tmp_path))
    assert result.status == Status.PASS
    assert "HISTORY.md" in result.details

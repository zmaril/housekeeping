from types import SimpleNamespace

from housekeeper.checks.codespell import codespell
from housekeeper.registry import Status


def ctx(tmp_path):
    return SimpleNamespace(workdir=tmp_path)


def workflow(tmp_path, text):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text(text)


def test_no_ci_fails(tmp_path):
    result = codespell(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "no CI workflow runs codespell" in result.details


def test_ci_wired_passes(tmp_path):
    workflow(tmp_path, "steps:\n  - uses: codespell-project/actions-codespell@v2\n")
    result = codespell(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "ci.yml" in result.details


def test_config_alone_is_not_enough(tmp_path):
    # A .codespellrc without CI wiring still fails — the check is about CI.
    (tmp_path / ".codespellrc").write_text("[codespell]\n")
    assert codespell(ctx(tmp_path)).status == Status.FAIL

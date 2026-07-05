from conftest import Ctx, write_wf

from housekeeper.checks.codespell import codespell
from housekeeper.registry import Status


def test_no_ci_fails(tmp_path):
    result = codespell(Ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "no CI workflow runs codespell" in result.details


def test_ci_wired_passes(tmp_path):
    write_wf(
        tmp_path, "ci.yml", "steps:\n  - uses: codespell-project/actions-codespell@v2\n"
    )
    result = codespell(Ctx(tmp_path))
    assert result.status == Status.PASS
    assert "ci.yml" in result.details


def test_config_alone_is_not_enough(tmp_path):
    # A .codespellrc without CI wiring still fails — the check is about CI.
    (tmp_path / ".codespellrc").write_text("[codespell]\n")
    assert codespell(Ctx(tmp_path)).status == Status.FAIL

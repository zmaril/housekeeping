from conftest import Ctx, write_wf

from housekeeper.checks.vale import vale
from housekeeper.registry import Status


def test_no_config_fails(tmp_path):
    result = vale(Ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "no .vale.ini" in result.details


def test_missing_styles_path_fails(tmp_path):
    (tmp_path / ".vale.ini").write_text("StylesPath = styles\n")
    write_wf(tmp_path, "ci.yml", "steps:\n  - uses: errata-ai/vale-action@reviewdog\n")
    result = vale(Ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "StylesPath" in result.details


def test_config_without_ci_fails(tmp_path):
    (tmp_path / ".vale.ini").write_text("StylesPath = styles\n")
    (tmp_path / "styles").mkdir()
    result = vale(Ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "no CI workflow runs vale" in result.details


def test_config_styles_and_ci_pass(tmp_path):
    (tmp_path / ".vale.ini").write_text(
        "StylesPath = styles\n[*.md]\nBasedOnStyles = Vale\n"
    )
    (tmp_path / "styles").mkdir()
    write_wf(tmp_path, "ci.yml", "steps:\n  - uses: errata-ai/vale-action@reviewdog\n")
    assert vale(Ctx(tmp_path)).status == Status.PASS


def test_config_without_styles_path_and_ci_pass(tmp_path):
    # StylesPath is optional; a .vale.ini with none is fine as long as vale runs.
    (tmp_path / ".vale.ini").write_text("[*.md]\nBasedOnStyles = proselint\n")
    write_wf(tmp_path, "ci.yml", "steps:\n  - run: vale docs/\n")
    assert vale(Ctx(tmp_path)).status == Status.PASS

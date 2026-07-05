from types import SimpleNamespace

from housekeeper.checks.stylelint import stylelint
from housekeeper.registry import Status


def ctx(tmp_path):
    return SimpleNamespace(workdir=tmp_path)


def workflow(tmp_path, text):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text(text)


def test_no_stylesheets_skips(tmp_path):
    assert stylelint(ctx(tmp_path)).status == Status.SKIP


def test_vendored_stylesheet_does_not_count(tmp_path):
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "index.css").write_text("a{}")
    assert stylelint(ctx(tmp_path)).status == Status.SKIP


def test_stylesheet_without_config_fails(tmp_path):
    (tmp_path / "app.css").write_text("a{}")
    result = stylelint(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "no stylelint config" in result.details


def test_config_without_ci_fails(tmp_path):
    (tmp_path / "app.scss").write_text("a{}")
    (tmp_path / ".stylelintrc.json").write_text("{}")
    result = stylelint(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "no CI workflow runs it" in result.details


def test_config_and_ci_pass(tmp_path):
    (tmp_path / "app.css").write_text("a{}")
    (tmp_path / ".stylelintrc.json").write_text("{}")
    workflow(tmp_path, "steps:\n  - run: npx stylelint '**/*.css'\n")
    assert stylelint(ctx(tmp_path)).status == Status.PASS


def test_package_json_config_counts(tmp_path):
    (tmp_path / "app.css").write_text("a{}")
    (tmp_path / "package.json").write_text('{"stylelint": {"rules": {}}}')
    workflow(tmp_path, "steps:\n  - run: npx stylelint .\n")
    result = stylelint(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "package.json" in result.details


def test_config_present_but_no_stylesheets_still_checks_ci(tmp_path):
    # A repo that keeps a stylelint config around but has no CSS yet shouldn't
    # skip silently — the config implies intent, so hold it to the CI wiring.
    (tmp_path / ".stylelintrc.json").write_text("{}")
    assert stylelint(ctx(tmp_path)).status == Status.FAIL

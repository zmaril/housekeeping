from types import SimpleNamespace

from housekeeper.checks.scripts import scripts
from housekeeper.config import Config
from housekeeper.registry import Status


def ctx_for(tmp_path, overrides=None):
    return SimpleNamespace(workdir=tmp_path, config=Config(overrides))


def make_dev(tmp_path, mentioned=True, dir_name="scripts", dev_name="dev.sh"):
    """A repo that satisfies the check: scripts/dev.sh + README mention."""
    d = tmp_path / dir_name
    d.mkdir(parents=True, exist_ok=True)
    (d / dev_name).write_text("#!/bin/sh\nuv sync\n")
    body = "# repo\n\nRun `./{}/{}` to set up.\n".format(dir_name, dev_name)
    (tmp_path / "README.md").write_text(body if mentioned else "# repo\n\nnothing\n")


def test_all_in_place_passes(tmp_path):
    make_dev(tmp_path)
    (tmp_path / "scripts" / "build.sh").write_text("#!/bin/sh\n")
    assert scripts(ctx_for(tmp_path)).status == Status.PASS


def test_missing_dev_script_fails(tmp_path):
    (tmp_path / "README.md").write_text("# repo\n\nwords\n")
    result = scripts(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "scripts/dev.sh" in result.details


def test_dev_present_but_not_in_readme_fails(tmp_path):
    make_dev(tmp_path, mentioned=False)
    result = scripts(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "not mentioned in the README" in result.details


def test_stray_script_at_root_flagged(tmp_path):
    make_dev(tmp_path)
    (tmp_path / "deploy.sh").write_text("#!/bin/sh\n")
    result = scripts(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "deploy.sh" in result.details


def test_stray_script_in_subdir_flagged(tmp_path):
    make_dev(tmp_path)
    sub = tmp_path / "tools"
    sub.mkdir()
    (sub / "release.sh").write_text("#!/bin/sh\n")
    result = scripts(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "tools/release.sh" in result.details


def test_hidden_and_vendor_dirs_ignored(tmp_path):
    make_dev(tmp_path)
    for rel in (".githooks/pre-commit.sh", ".git/hooks/x.sh", "node_modules/p/x.sh"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
    assert scripts(ctx_for(tmp_path)).status == Status.PASS


def test_allowlist_lets_a_stray_pass(tmp_path):
    make_dev(tmp_path)
    (tmp_path / "install.sh").write_text("#!/bin/sh\n")
    overrides = {"scripts": {"allow": ["install.sh"]}}
    assert scripts(ctx_for(tmp_path, overrides)).status == Status.PASS


def test_configured_dir_and_name(tmp_path):
    make_dev(tmp_path, dir_name="bin", dev_name="setup.sh")
    overrides = {"scripts": {"dir": "bin", "dev": "setup.sh"}}
    assert scripts(ctx_for(tmp_path, overrides)).status == Status.PASS

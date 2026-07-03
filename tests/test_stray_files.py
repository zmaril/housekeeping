from types import SimpleNamespace

from housekeeper.checks.stray_files import stray_files
from housekeeper.config import Config
from housekeeper.registry import Status


def ctx_for(tmp_path, overrides=None):
    return SimpleNamespace(workdir=tmp_path, config=Config(overrides))


def test_conventional_files_pass(tmp_path):
    for name in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE.txt",
                 "CODE_OF_CONDUCT.md", "AGENTS.md"):
        (tmp_path / name).write_text("x")
    assert stray_files(ctx_for(tmp_path)).status == Status.PASS


def test_stray_notes_flagged(tmp_path):
    (tmp_path / "README.md").write_text("x")
    (tmp_path / "todo.txt").write_text("x")
    (tmp_path / "notes-2024.md").write_text("x")
    result = stray_files(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "todo.txt" in result.details and "notes-2024.md" in result.details


def test_config_allowlist(tmp_path):
    (tmp_path / "DESIGN.md").write_text("x")
    overrides = {"stray-files": {"allow": ["DESIGN.md"]}}
    assert stray_files(ctx_for(tmp_path, overrides)).status == Status.PASS


def test_non_text_files_ignored(tmp_path):
    (tmp_path / "action.yml").write_text("x")
    (tmp_path / "Cargo.toml").write_text("x")
    assert stray_files(ctx_for(tmp_path)).status == Status.PASS

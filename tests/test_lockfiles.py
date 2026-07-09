"""The lockfiles check: native-tool sync plus the git-history staleness fallback.

These exercise the heuristic path, so they need a REAL git repo in tmp_path with
controlled commit timestamps (set via GIT_AUTHOR_DATE / GIT_COMMITTER_DATE, which
conftest's autouse fixture leaves alone). The ruby and go ecosystems have no
native sync check, so the heuristic runs with no external dependency.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from housekeeper.checks.lockfiles import lockfiles
from housekeeper.config import Config
from housekeeper.languages import ECOSYSTEMS
from housekeeper.registry import Status

EARLY = "2026-01-01T00:00:00"
LATE = "2026-06-01T00:00:00"


def git(tmp_path: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ}
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", *args],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
    )


def init_repo(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")


def commit(tmp_path: Path, files: list[str], date: str, message: str) -> None:
    for f in files:
        git(tmp_path, "add", f)
    git(tmp_path, "commit", "-q", "-m", message, date=date)


def ctx_for(tmp_path: Path, ecosystems: list) -> SimpleNamespace:
    return SimpleNamespace(workdir=tmp_path, ecosystems=ecosystems, config=Config())


def test_same_commit_passes(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
    (tmp_path / "Gemfile.lock").write_text("GEM\n")
    commit(tmp_path, ["Gemfile", "Gemfile.lock"], EARLY, "add ruby deps")

    result = lockfiles(ctx_for(tmp_path, [ECOSYSTEMS["ruby"]]))
    assert result.status == Status.PASS
    assert "git history" in result.details


def test_manifest_newer_fails_stale(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "Gemfile.lock").write_text("GEM\n")
    commit(tmp_path, ["Gemfile.lock"], EARLY, "add lockfile")
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
    commit(tmp_path, ["Gemfile"], LATE, "add manifest later")

    result = lockfiles(ctx_for(tmp_path, [ECOSYSTEMS["ruby"]]))
    assert result.status == Status.FAIL
    assert "likely stale" in result.details


def test_missing_lockfile_fails(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
    commit(tmp_path, ["Gemfile"], EARLY, "add manifest only")

    result = lockfiles(ctx_for(tmp_path, [ECOSYSTEMS["ruby"]]))
    assert result.status == Status.FAIL
    assert "missing" in result.details


def test_gitignored_lockfile_fails(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
    (tmp_path / ".gitignore").write_text("Gemfile.lock\n")
    (tmp_path / "Gemfile.lock").write_text("GEM\n")
    commit(tmp_path, ["Gemfile", ".gitignore"], EARLY, "ignore the lockfile")

    result = lockfiles(ctx_for(tmp_path, [ECOSYSTEMS["ruby"]]))
    assert result.status == Status.FAIL
    assert "gitignored" in result.details


def test_go_manifest_newer_fails_stale(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "go.sum").write_text("example.com/x v1.0.0 h1:abc\n")
    commit(tmp_path, ["go.sum"], EARLY, "add go.sum")
    (tmp_path / "go.mod").write_text("module example.com/x\n")
    commit(tmp_path, ["go.mod"], LATE, "add go.mod later")

    result = lockfiles(ctx_for(tmp_path, [ECOSYSTEMS["go"]]))
    assert result.status == Status.FAIL
    assert "likely stale" in result.details


def test_native_tool_absent_falls_back_to_heuristic(tmp_path, monkeypatch):
    """A native-check ecosystem whose tool is missing uses the heuristic rather
    than silently reporting the lockfile as unverified."""
    import housekeeper.checks.lockfiles as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _tool: None)
    init_repo(tmp_path)
    (tmp_path / "Cargo.lock").write_text("# lock\n")
    commit(tmp_path, ["Cargo.lock"], EARLY, "add Cargo.lock")
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n")
    commit(tmp_path, ["Cargo.toml"], LATE, "add Cargo.toml later")

    result = lockfiles(ctx_for(tmp_path, [ECOSYSTEMS["cargo"]]))
    assert result.status == Status.FAIL
    assert "likely stale" in result.details


def test_no_lockfile_ecosystems_skips(tmp_path):
    result = lockfiles(ctx_for(tmp_path, []))
    assert result.status == Status.SKIP

"""Shared test helpers: a workflow writer and a minimal RepoContext stand-in.

Kept here (once) rather than copied per test module — straitjacket's duplication
check grades this repo's own tests, and it's right to.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def write_wf(tmp_path: Path, name: str, content: str) -> None:
    """Write a workflow file into tmp_path/.github/workflows/."""
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


class Ctx:
    """The slice of RepoContext the clone-only CI checks read: a workdir."""

    def __init__(self, tmp_path: Path):
        self.workdir = tmp_path


@pytest.fixture(autouse=True)
def _no_ambient_git_env(monkeypatch):
    """git exports GIT_DIR / GIT_INDEX_FILE / GIT_WORK_TREE to hooks; when the
    suite runs under pre-commit or pre-push, every git subprocess a test
    spawns inherits them and operates on the REAL repo instead of its temp
    fixture — `git add -A` in a tmp dir once staged this repo's deletion into
    the live index mid-commit. Tests always get a clean git environment."""
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)

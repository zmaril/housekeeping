"""Shared test helpers: a workflow writer and a minimal RepoContext stand-in.

Kept here (once) rather than copied per test module — straitjacket's duplication
check grades this repo's own tests, and it's right to.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def load_workflow(content: str):
    """Parse a workflow YAML, returning (data, on-triggers).

    YAML 1.1 parses a bare `on` key as the boolean True, so the trigger table
    hides under data[True]; unwrap it here once rather than in every
    workflow-shape test.
    """
    data = yaml.safe_load(content)
    on = data.get("on", data.get(True))
    return data, on


def write_wf(tmp_path: Path, name: str, content: str) -> None:
    """Write a workflow file into tmp_path/.github/workflows/."""
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


class Ctx:
    """The slice of RepoContext the clone-only CI checks read: a workdir."""

    def __init__(self, tmp_path: Path):
        self.workdir = tmp_path


class StrictCtx:
    """A RepoContext stand-in for the strict-gated workflow checks
    (auto-update-pr-branches, request-conflict-rebase) and strict_workflow_gate.

    Feeds strict_flag a branch-protection read and the check a workdir. `strict`
    None models the no-admin case: both protection reads fold to None, which
    strict_flag reports as unreadable. True/False returns a ruleset rule carrying
    that strict policy.
    """

    repo, default_branch = "o/r", "main"

    def __init__(self, tmp_path: Path, strict: bool | None = None):
        self.workdir = tmp_path
        self._strict = strict

    def try_api(self, path, none_on=(404,), **kw):
        if self._strict is None or "/rules/branches/" not in path:
            return None
        params = {"strict_required_status_checks_policy": self._strict}
        return [{"type": "required_status_checks", "parameters": params}]


@pytest.fixture(autouse=True)
def _no_ambient_git_env(monkeypatch):
    """git exports GIT_DIR / GIT_INDEX_FILE / GIT_WORK_TREE to hooks; when the
    suite runs under pre-commit or pre-push, every git subprocess a test
    spawns inherits them and operates on the REAL repo instead of its temp
    fixture — `git add -A` in a tmp dir once staged this repo's deletion into
    the live index mid-commit. Tests always get a clean git environment."""
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)

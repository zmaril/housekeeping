"""Shared test helpers: a workflow writer and a minimal RepoContext stand-in.

Kept here (once) rather than copied per test module — straitjacket's duplication
check grades this repo's own tests, and it's right to.
"""

from __future__ import annotations

from pathlib import Path


def write_wf(tmp_path: Path, name: str, content: str) -> None:
    """Write a workflow file into tmp_path/.github/workflows/."""
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


class Ctx:
    """The slice of RepoContext the clone-only CI checks read: a workdir."""

    def __init__(self, tmp_path: Path):
        self.workdir = tmp_path

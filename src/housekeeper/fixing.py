"""Shared machinery for fixes: confirmation, and the branch → commit → push → PR flow.

Every fix explains itself and asks before touching anything. File-side fixes
land on a housekeeping/<check> branch; nothing is ever pushed to the default
branch, and push + PR only happen on an explicit yes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.console import Console

from .context import RepoContext, run

console = Console()


def confirm(prompt: str) -> bool:
    try:
        # \[ so rich prints the hint instead of eating it as markup
        answer = console.input(f"[bold]{prompt}[/bold] \\[y/n] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def apply_file_fix(
    ctx: RepoContext,
    check_name: str,
    describe: str,
    why: str,
    write_changes: Callable[[Path], list[Path]],
    commit_message: str,
) -> None:
    """Run a fix that edits files. write_changes gets the workdir and returns changed paths.

    `why` is required on purpose: every toggle explains itself before asking.
    """
    workdir = ctx.ensure_workdir()

    dirty = run(["git", "status", "--porcelain"], cwd=workdir)
    if dirty.stdout.strip():
        console.print(
            f"[red]working tree at {workdir} is dirty — commit or stash first, then re-run[/red]"
        )
        return

    console.print(f"\nThis fix will: {describe}")
    console.print(f"[dim]Why: {why}[/dim]")
    console.print(
        f"Changes go on a new branch [cyan]housekeeping/{check_name}[/cyan] in {workdir}."
    )
    if not confirm("Write the changes?"):
        console.print("Nothing done.")
        return

    branch = f"housekeeping/{check_name}"
    switched = run(["git", "switch", "-c", branch], cwd=workdir)
    if switched.returncode != 0:
        console.print(
            f"[red]could not create branch {branch}:[/red] {switched.stderr.strip()}"
        )
        return

    changed = write_changes(workdir)
    for path in changed:
        run(["git", "add", str(path)], cwd=workdir)

    diff = run(["git", "diff", "--cached"], cwd=workdir)
    console.print(diff.stdout or "(no diff?)")

    if not confirm(f"Commit to {branch}?"):
        console.print(
            f"Changes left staged on [cyan]{branch}[/cyan], uncommitted. "
            f"`git switch -` to go back."
        )
        return
    commit = run(["git", "commit", "-m", commit_message], cwd=workdir)
    if commit.returncode != 0:
        console.print(f"[red]commit failed:[/red] {commit.stderr.strip()}")
        return
    console.print(f"Committed to [cyan]{branch}[/cyan].")

    if not confirm("Push the branch and open a PR?"):
        console.print(
            f"Not pushed. When ready: git push -u origin {branch} && gh pr create"
        )
        return
    push = run(["git", "push", "-u", "origin", branch], cwd=workdir)
    if push.returncode != 0:
        console.print(f"[red]push failed:[/red] {push.stderr.strip()}")
        return
    pr = run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            commit_message,
            "--body",
            f"Automated housekeeping fix for the `{check_name}` check.",
        ],
        cwd=workdir,
    )
    if pr.returncode != 0:
        console.print(f"[red]gh pr create failed:[/red] {pr.stderr.strip()}")
        return
    console.print(f"PR opened: {pr.stdout.strip()}")

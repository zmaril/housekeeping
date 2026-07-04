"""Repo has a description, topics, and issues enabled."""

from __future__ import annotations

from ..context import RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed


@check("repo-meta", needs=("api",))
def repo_meta(ctx: RepoContext):
    info = ctx.repo_info
    problems = []
    if not (info.get("description") or "").strip():
        problems.append("no description")
    if not info.get("topics"):
        problems.append("no topics")
    if not info.get("has_issues"):
        problems.append("issues disabled")
    if problems:
        return failed("; ".join(problems))
    return passed(f"description + {len(info['topics'])} topic(s) set, issues enabled")


@fix_for("repo-meta")
def fix(ctx: RepoContext):
    info = ctx.repo_info

    if not (info.get("description") or "").strip():
        console.print(
            "\n[dim]Why: the description shows in repo lists, search results, and link "
            "previews — for most people it's their first contact with the project.[/dim]"
        )
        description = console.input("Description (empty to skip): ").strip()
        if description and confirm(f"Set description to {description!r}?"):
            ctx.api(
                f"repos/{ctx.repo}", method="PATCH", input={"description": description}
            )
            console.print("[green]description set[/green]")

    if not info.get("topics"):
        console.print(
            "\n[dim]Why: topics are how GitHub search and explore surface the repo — "
            "no topics means nobody finds it by browsing.[/dim]"
        )
        raw = console.input("Topics, comma-separated (empty to skip): ").strip()
        topics = [t.strip().lower() for t in raw.split(",") if t.strip()]
        if topics and confirm(f"Set topics to {topics}?"):
            ctx.api(f"repos/{ctx.repo}/topics", method="PUT", input={"names": topics})
            console.print("[green]topics set[/green]")

    if not info.get("has_issues"):
        console.print(
            "\n[dim]Why: issues give users somewhere to report bugs and ask questions — "
            "with them off, feedback lands on social media or nowhere.[/dim]"
        )
        if confirm("Enable issues?"):
            ctx.api(f"repos/{ctx.repo}", method="PATCH", input={"has_issues": True})
            console.print("[green]issues enabled[/green]")

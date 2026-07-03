"""Secret scanning + push protection enabled (free on public repos)."""

from __future__ import annotations

from ..context import RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped


def _status(info: dict, key: str) -> str:
    return ((info.get("security_and_analysis") or {}).get(key) or {}).get("status", "disabled")


@check("secret-scanning", needs=("api",))
def secret_scanning(ctx: RepoContext):
    scanning = _status(ctx.repo_info, "secret_scanning")
    push_protection = _status(ctx.repo_info, "secret_scanning_push_protection")

    if ctx.visibility == "private" and scanning != "enabled":
        return skipped("secret scanning not enabled",
                       note="needs GitHub Advanced Security on private repos")

    problems = []
    if scanning != "enabled":
        problems.append("secret scanning disabled")
    if push_protection != "enabled":
        problems.append("push protection disabled")
    if problems:
        return failed("; ".join(problems))
    return passed("secret scanning + push protection enabled")


@fix_for("secret-scanning")
def fix(ctx: RepoContext):
    console.print(
        "\nSecret scanning finds committed credentials (API keys, tokens) and alerts "
        "you; push protection blocks them at push time — before they're in history, "
        "where revoking is the only cure."
    )
    if not confirm(f"Enable secret scanning + push protection on {ctx.repo}?"):
        console.print("Nothing done.")
        return
    ctx.api(f"repos/{ctx.repo}", method="PATCH", input={
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }
    })
    console.print("[green]secret scanning + push protection enabled[/green]")

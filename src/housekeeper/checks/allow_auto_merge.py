"""allow-auto-merge: the repo's GitHub auto-merge setting matches the declared preference.

Auto-merge lets a PR merge itself the moment its required checks go green - no human
at the merge moment. This fleet's default is branch-protection + required-checks +
a person doing the merge, so the default preference is OFF; a repo that wants
auto-merge sets `[allow-auto-merge] enabled = true` in .housekeeping.toml. The check
just asserts GitHub's actual setting matches the declared preference either way.
Auto-merge never bypasses branch protection or required checks - it waits for them -
so ON is a legitimate choice; this is a preference, not a hardcoded polarity.
"""

from __future__ import annotations

from ..context import GhError, RepoContext
from ..fixing import confirm, console
from ..registry import check, failed, fix_for, passed, skipped


def _wanted(ctx: RepoContext) -> bool:
    return bool(ctx.config.section("allow-auto-merge").get("enabled", False))


@check("allow-auto-merge", needs=("api",))
def allow_auto_merge(ctx: RepoContext):
    want = _wanted(ctx)
    have = ctx.repo_info.get("allow_auto_merge")
    if have is None:
        return skipped(
            "auto-merge setting not visible to this token",
            note="the repo object did not include allow_auto_merge",
        )
    if bool(have) == want:
        state = "on" if want else "off"
        return passed(f"auto-merge is {state}, as declared")
    return failed(
        f"auto-merge is {'on' if have else 'off'} but .housekeeping.toml "
        f"declares {'on' if want else 'off'}",
        note="set [allow-auto-merge] enabled in .housekeeping.toml, "
        "or run `housekeeper fix allow-auto-merge` (needs an admin token)",
    )


@fix_for("allow-auto-merge")
def fix(ctx: RepoContext):
    want = _wanted(ctx)
    have = ctx.repo_info.get("allow_auto_merge")
    if have is not None and bool(have) == want:
        console.print(
            "[green]auto-merge already matches the declared preference[/green]"
        )
        return
    target = "on" if want else "off"
    console.print(
        f"\nThis will turn auto-merge [cyan]{target}[/cyan] on {ctx.repo} to match "
        "the declared preference."
    )
    console.print(
        "[dim]Why: auto-merge merges a PR automatically once its required checks pass. "
        "This fleet's default is a human at the merge, so the preference defaults off; "
        "a repo opts in via [allow-auto-merge] enabled = true.[/dim]"
    )
    if not confirm(f"Set allow_auto_merge = {want}?"):
        console.print("Nothing done.")
        return
    try:
        ctx.api(f"repos/{ctx.repo}", method="PATCH", input={"allow_auto_merge": want})
    except GhError as e:
        if e.status == 403:
            console.print(
                "[red]token lacks admin (HTTP 403)[/red] - re-run with an admin token, "
                "or flip it by hand in repo Settings -> General -> Pull Requests."
            )
            return
        raise
    console.print(f"[green]auto-merge set {target}.[/green]")

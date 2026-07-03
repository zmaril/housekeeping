"""dependabot.yml covers every detected ecosystem; alerts + security updates enabled."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..context import GhError, RepoContext
from ..fixing import apply_file_fix, confirm, console
from ..registry import check, failed, fix_for, passed


def dependabot_path(workdir: Path) -> Path | None:
    for name in ("dependabot.yml", "dependabot.yaml"):
        path = workdir / ".github" / name
        if path.is_file():
            return path
    return None


def covered_ecosystems(path: Path) -> set[str]:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return set()
    return {u.get("package-ecosystem", "") for u in data.get("updates", [])
            if isinstance(u, dict)}


def uncovered(ctx: RepoContext, covered: set[str]) -> list[str]:
    missing = []
    for eco in ctx.ecosystems:
        acceptable = {eco.dependabot, *eco.dependabot_alts}
        if not (acceptable & covered):
            missing.append(f"{eco.name} (wants {eco.dependabot})")
    return missing


def _setting(ctx: RepoContext, path: str) -> bool | None:
    """True enabled, False disabled, None if the token can't see it (403)."""
    try:
        result = ctx.api(path)
    except GhError as e:
        if e.status == 404:
            return False
        if e.status == 403:
            return None
        raise
    if isinstance(result, dict):
        return bool(result.get("enabled"))
    return True  # 204-style empty success


@check("dependabot", needs=("clone", "api"))
def dependabot(ctx: RepoContext):
    problems, unknown = [], []
    path = dependabot_path(ctx.workdir)
    if path is None:
        problems.append("no .github/dependabot.yml")
    else:
        missing = uncovered(ctx, covered_ecosystems(path))
        if missing:
            problems.append(f"dependabot.yml missing ecosystems: {', '.join(missing)}")

    for label, api_path in (
        ("vulnerability alerts", f"repos/{ctx.repo}/vulnerability-alerts"),
        ("automated security fixes", f"repos/{ctx.repo}/automated-security-fixes"),
    ):
        state = _setting(ctx, api_path)
        if state is False:
            problems.append(f"{label} disabled")
        elif state is None:
            unknown.append(label)

    note = (f"not visible to this token: {', '.join(unknown)} — "
            "run housekeeper locally for full coverage") if unknown else ""
    if problems:
        return failed("; ".join(problems), note)
    return passed("dependabot.yml covers all ecosystems"
                  + ("" if unknown else "; alerts + security fixes on"), note)


UPDATE_TEMPLATE = """\
  - package-ecosystem: "{eco}"
    directory: "/"
    schedule:
      interval: "weekly"
"""


@fix_for("dependabot")
def fix(ctx: RepoContext):
    # API-side settings first — cheap, reversible, no commit needed.
    if ctx.try_api(f"repos/{ctx.repo}/vulnerability-alerts") is None:
        console.print(
            "\nVulnerability alerts: GitHub checks your dependency graph against its "
            "advisory database and notifies you when something you depend on has a "
            "known CVE — otherwise you find out from the incident."
        )
        if confirm(f"Enable vulnerability alerts on {ctx.repo}?"):
            ctx.api(f"repos/{ctx.repo}/vulnerability-alerts", method="PUT")
            console.print("[green]vulnerability alerts enabled[/green]")
    fixes_state = ctx.try_api(f"repos/{ctx.repo}/automated-security-fixes")
    if not (isinstance(fixes_state, dict) and fixes_state.get("enabled")):
        console.print(
            "\nAutomated security fixes: when an alert fires, Dependabot opens a PR "
            "bumping the vulnerable dependency to the patched version — the fix "
            "arrives as a reviewable diff instead of a todo."
        )
        if confirm(f"Enable automated security fixes on {ctx.repo}?"):
            ctx.api(f"repos/{ctx.repo}/automated-security-fixes", method="PUT")
            console.print("[green]automated security fixes enabled[/green]")

    path = dependabot_path(ctx.workdir)
    covered = covered_ecosystems(path) if path else set()
    missing = uncovered(ctx, covered)
    if not missing:
        return
    to_add = [eco.dependabot for eco in ctx.ecosystems
              if not ({eco.dependabot, *eco.dependabot_alts} & covered)]

    def write(workdir: Path) -> list[Path]:
        target = dependabot_path(workdir) or workdir / ".github" / "dependabot.yml"
        if target.is_file():
            content = target.read_text().rstrip("\n") + "\n"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = "version: 2\nupdates:\n"
        content += "".join(UPDATE_TEMPLATE.format(eco=eco) for eco in to_add)
        target.write_text(content)
        return [target]

    apply_file_fix(
        ctx, "dependabot",
        describe=f"add weekly dependabot updates for: {', '.join(to_add)}",
        why="weekly update PRs keep dependencies moving in small, reviewable bumps — "
            "the alternative is one scary mass upgrade a year later",
        write_changes=write,
        commit_message="chore: cover all ecosystems in dependabot.yml",
    )

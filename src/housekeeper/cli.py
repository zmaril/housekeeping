"""housekeeper: check / fix / report, one repo at a time."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from . import checks  # noqa: F401 — importing registers every check
from .context import CACHE_DIR, GhError, RepoContext, repo_from_cwd
from .registry import CHECKS, Result, Status

console = Console()
RESULTS_DIR = CACHE_DIR / "results"

STYLE = {
    Status.PASS: ("✓", "green"),
    Status.FAIL: ("✗", "red"),
    Status.SKIP: ("–", "dim"),
    Status.ERROR: ("!", "yellow"),
}


def resolve_repo(arg: str | None) -> str:
    repo = arg or repo_from_cwd()
    if not repo:
        console.print("[red]not inside a GitHub checkout — pass owner/repo explicitly[/red]")
        sys.exit(2)
    return repo


def select_checks(only: str | None) -> list:
    if not only:
        return list(CHECKS.values())
    names = [n.strip() for n in only.split(",")]
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        console.print(f"[red]unknown checks: {', '.join(unknown)}[/red] "
                      f"(available: {', '.join(CHECKS)})")
        sys.exit(2)
    return [CHECKS[n] for n in names]


def cmd_check(args) -> int:
    repo = resolve_repo(args.repo)
    ctx = RepoContext(repo)
    selected = select_checks(args.only)

    try:
        visibility = ctx.visibility
    except GhError as e:
        console.print(f"[red]cannot reach {repo}:[/red] {e}")
        return 2

    if any("clone" in c.needs for c in selected):
        ctx.ensure_workdir()

    rows = []
    for check in selected:
        severity = ctx.config.severity(check.name, visibility)
        if severity == "off":
            continue
        try:
            result = check.run(ctx)
        except Exception as e:  # a broken check shouldn't sink the run
            result = Result(Status.ERROR, f"check crashed: {e}")
        rows.append({
            "check": check.name,
            "status": result.status.value,
            "severity": severity,
            "details": result.details,
            "note": result.note,
            "fixable": check.fixable,
        })

    payload = {
        "repo": repo,
        "visibility": visibility,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": rows,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / f"{repo.replace('/', '--')}.json"
    results_path.write_text(json.dumps(payload, indent=2) + "\n")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        render(payload)
        console.print(f"[dim]results saved to {results_path}[/dim]")

    return exit_code(payload)


def cmd_fix(args) -> int:
    repo = resolve_repo(args.repo)
    if args.check not in CHECKS:
        console.print(f"[red]unknown check {args.check!r}[/red] (available: {', '.join(CHECKS)})")
        return 2
    check = CHECKS[args.check]
    if check.fix is None:
        console.print(f"[yellow]{check.name} has no automated fix[/yellow] — see the check details for what to do")
        return 2

    ctx = RepoContext(repo)
    if "clone" in check.needs:
        ctx.ensure_workdir()
    result = check.run(ctx)
    if result.status == Status.PASS:
        console.print(f"[green]{check.name} already passes[/green] — nothing to fix")
        return 0
    if result.status == Status.SKIP:
        console.print(f"[dim]{check.name} is skipped for this repo:[/dim] {result.details}")
        return 0

    console.print(f"[red]{check.name}[/red]: {result.details}")
    if result.note:
        console.print(f"[dim]{result.note}[/dim]")
    check.fix(ctx)
    return 0


def cmd_report(args) -> int:
    repo = resolve_repo(args.repo)
    results_path = RESULTS_DIR / f"{repo.replace('/', '--')}.json"
    if not results_path.is_file():
        console.print(f"[red]no saved results for {repo}[/red] — run `housekeeper check` first")
        return 2
    payload = json.loads(results_path.read_text())
    render(payload)
    return exit_code(payload)


def render(payload: dict) -> None:
    table = Table(title=f"{payload['repo']} ({payload['visibility']}) — {payload['checked_at']}")
    table.add_column("check")
    table.add_column("status")
    table.add_column("details", overflow="fold")
    table.add_column("note", style="dim", overflow="fold")
    for row in payload["results"]:
        symbol, style = STYLE[Status(row["status"])]
        status = f"[{style}]{symbol} {row['status']}[/{style}]"
        if row["status"] == "fail" and row["severity"] == "recommended":
            status = "[yellow]! warn[/yellow]"
        details = row["details"]
        if row["status"] == "fail" and row["fixable"]:
            details += f"  [cyan](housekeeper fix {row['check']})[/cyan]"
        table.add_row(row["check"], status, details, row["note"])
    console.print(table)


def exit_code(payload: dict) -> int:
    bad = [r for r in payload["results"]
           if r["status"] in ("fail", "error") and r["severity"] == "required"]
    return 1 if bad else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="housekeeper",
                                     description="Check that a GitHub repo is in good order.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="run checks (read-only)")
    p_check.add_argument("repo", nargs="?", help="owner/repo (default: inferred from cwd)")
    p_check.add_argument("--only", help="comma-separated check names")
    p_check.add_argument("--json", action="store_true", help="print results as JSON")
    p_check.set_defaults(func=cmd_check)

    p_fix = sub.add_parser("fix", help="fix one failing check (asks before changing anything)")
    p_fix.add_argument("check", help="check name to fix")
    p_fix.add_argument("repo", nargs="?", help="owner/repo (default: inferred from cwd)")
    p_fix.set_defaults(func=cmd_fix)

    p_report = sub.add_parser("report", help="re-render the last check run")
    p_report.add_argument("repo", nargs="?", help="owner/repo (default: inferred from cwd)")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    sys.exit(args.func(args))

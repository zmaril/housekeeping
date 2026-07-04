"""housekeeper: check / fix / report, one repo at a time."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def audit(repo: str, only: str | None = None) -> dict:
    """Run the checks against one repo and save+return the payload."""
    ctx = RepoContext(repo)
    selected = select_checks(only)
    visibility = ctx.visibility  # GhError propagates to the caller

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
    return payload


def cmd_check(args) -> int:
    repo = resolve_repo(args.repo)
    try:
        payload = audit(repo, args.only)
    except GhError as e:
        console.print(f"[red]cannot reach {repo}:[/red] {e}")
        return 2

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        render(payload)
        console.print(f"[dim]results saved to {RESULTS_DIR / (repo.replace('/', '--') + '.json')}[/dim]")

    # Inside GitHub Actions, also render into the job summary.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as summary:
            summary.write(render_markdown(payload) + "\n")

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


def load_manifest_or_exit(path_arg: str | None):
    from .captain import load_manifest

    path = Path(path_arg or "housecaptain.toml")
    if not path.is_file():
        console.print(f"[red]no manifest at {path}[/red] — pass a housecaptain.toml path")
        sys.exit(2)
    return load_manifest(path)


CAPTAIN_STYLE = {"ok": ("✓", "green"), "fail": ("✗", "red"),
                 "conflict": ("≠", "yellow"), "error": ("!", "yellow"),
                 "parked": ("–", "dim")}


def cmd_captain(args) -> int:
    from .captain import MemberReport, captain_member

    manifest = load_manifest_or_exit(args.manifest)
    reports = []
    for member in manifest.members:
        if member.parked:
            reports.append(MemberReport(member.repo, "parked",
                                        "in the fleet, not yet expected to self-audit",
                                        note=member.note))
            continue
        try:
            report = captain_member(RepoContext(member.repo), manifest.policy_checks,
                                    manifest.required_files)
        except GhError as e:
            report = MemberReport(member.repo, "error", f"api error: {e}")
        if member.note and not report.note:
            report.note = member.note
        reports.append(report)

    table = Table(title=f"{manifest.name} fleet — are the auditors on duty?")
    table.add_column("member")
    table.add_column("status")
    table.add_column("details", overflow="fold")
    table.add_column("note", style="dim", overflow="fold")
    lines = [f"### {manifest.name} fleet", "", "| member | status | details | note |",
             "|---|---|---|---|"]
    for report in reports:
        symbol, style = CAPTAIN_STYLE[report.status]
        table.add_row(report.repo, f"[{style}]{symbol} {report.status}[/{style}]",
                      report.details, report.note)
        cells = [report.repo, f"{symbol} {report.status}", report.details, report.note]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    console.print(table)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as summary:
            summary.write("\n".join(lines) + "\n")

    return 1 if any(r.status in ("fail", "conflict", "error") for r in reports) else 0


def cmd_fleet(args) -> int:
    manifest = load_manifest_or_exit(args.manifest)
    payloads: list[dict | None] = []
    for member in manifest.members:
        console.print(f"[dim]auditing {member.repo}…[/dim]")
        try:
            payloads.append(audit(member.repo))
        except GhError as e:
            console.print(f"[red]{member.repo}: api error: {e}[/red]")
            payloads.append(None)

    table = Table(title=f"{manifest.name} fleet — full audit")
    for column in ("member", "pass", "warn", "fail", "failing checks"):
        table.add_column(column, overflow="fold")
    worst = 0
    for member, payload in zip(manifest.members, payloads):
        if payload is None:
            table.add_row(member.repo, "-", "-", "-", "[yellow]unreachable[/yellow]")
            worst = 1
            continue
        rows = payload["results"]
        passed = sum(1 for r in rows if r["status"] == "pass")
        failing = [r for r in rows if r["status"] in ("fail", "error")]
        warns = [r for r in failing if r["severity"] == "recommended"]
        hard = [r for r in failing if r["severity"] == "required"]
        table.add_row(member.repo, str(passed), str(len(warns)), str(len(hard)),
                      ", ".join(r["check"] for r in hard) or "-")
        if hard:
            worst = 1
    console.print(table)
    console.print("[dim]per-repo detail: housekeeper report <owner/repo>[/dim]")
    return worst


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


# same symbols as the terminal table; straitjacket rightly objects to emoji
MD_ICON = {"pass": "✓", "fail": "✗", "skip": "–", "error": "!"}


def render_markdown(payload: dict) -> str:
    lines = [
        f"### housekeeping: {payload['repo']} ({payload['visibility']}) — {payload['checked_at']}",
        "",
        "| check | status | details | note |",
        "|---|---|---|---|",
    ]
    for row in payload["results"]:
        status = f"{MD_ICON[row['status']]} {row['status']}"
        if row["status"] == "fail" and row["severity"] == "recommended":
            status = "! warn"
        details = row["details"]
        if row["status"] == "fail" and row["fixable"]:
            details += f" — `housekeeper fix {row['check']}`"
        cells = [row["check"], status, details, row["note"]]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"


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

    p_captain = sub.add_parser(
        "captain", help="check every fleet member is auditing itself (API-only)")
    p_captain.add_argument("manifest", nargs="?", help="path to housecaptain.toml")
    p_captain.set_defaults(func=cmd_captain)

    p_fleet = sub.add_parser("fleet", help="full local audit of every fleet member")
    p_fleet.add_argument("manifest", nargs="?", help="path to housecaptain.toml")
    p_fleet.set_defaults(func=cmd_fleet)

    args = parser.parse_args()
    sys.exit(args.func(args))

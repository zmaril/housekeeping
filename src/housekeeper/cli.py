"""housekeeper: check / fix / report, one repo at a time."""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import checks  # noqa: F401 — importing registers every check
from .context import CACHE_DIR, GhError, RepoContext, repo_from_cwd
from .languages import detect_artifacts, detect_ecosystems, detect_typed_languages
from .registry import CHECKS, Result, Status

console = Console()
RESULTS_DIR = CACHE_DIR / "results"

STYLE = {
    Status.PASS: ("✓", "green"),
    Status.FAIL: ("✗", "red"),
    Status.SKIP: ("–", "dim"),
    Status.ERROR: ("!", "yellow"),
}


# Checks that grade the DEFAULT BRANCH's state or the repo's settings — things
# no pull request can change. On pull_request runs they inform instead of
# gate: failing a PR for main's redness is how the fix-carrying PR gets
# deadlocked (the same self-reference ci-green already excludes for its
# hosting workflow and the housekeeping family — see its docstring). They
# stay hard on push/schedule/local runs, where main's state is the point.
MAIN_STATE_CHECKS = frozenset(
    {"ci-green", "branch-protection", "required-checks", "strict-status-checks"}
)


def effective_severity(check_name: str, severity: str, event: str) -> tuple[str, bool]:
    """(severity, demoted): required main-state checks soften on PR events."""
    if (
        event == "pull_request"
        and severity == "required"
        and check_name in MAIN_STATE_CHECKS
    ):
        return "recommended", True
    return severity, False


def resolve_repo(arg: str | None) -> str:
    repo = arg or repo_from_cwd()
    if not repo:
        console.print(
            "[red]not inside a GitHub checkout — pass owner/repo explicitly[/red]"
        )
        sys.exit(2)
    return repo


def select_checks(only: str | None) -> list:
    if not only:
        return list(CHECKS.values())
    names = [n.strip() for n in only.split(",")]
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        console.print(
            f"[red]unknown checks: {', '.join(unknown)}[/red] "
            f"(available: {', '.join(CHECKS)})"
        )
        sys.exit(2)
    return [CHECKS[n] for n in names]


def fetch_activity(ctx: RepoContext) -> dict:
    """Open issues and PRs for the repo, for the dashboard's scrollable lists.

    Best-effort: an API hiccup yields empty lists rather than sinking the audit."""

    def item(it: dict) -> dict:
        return {"number": it["number"], "title": it["title"], "url": it["html_url"]}

    try:
        raw_issues = (
            ctx.api(
                f"repos/{ctx.repo}/issues", params={"state": "open", "per_page": 100}
            )
            or []
        )
    except GhError:
        raw_issues = []
    try:
        raw_pulls = (
            ctx.api(
                f"repos/{ctx.repo}/pulls", params={"state": "open", "per_page": 100}
            )
            or []
        )
    except GhError:
        raw_pulls = []

    # the issues endpoint also returns PRs — drop those (they carry a pull_request key)
    issues = [item(i) for i in raw_issues if "pull_request" not in i]
    pulls = [item(p) for p in raw_pulls]
    return {"issues": issues, "pulls": pulls}


def audit(repo: str, only: str | None = None) -> dict:
    """Run the checks against one repo and save+return the payload."""
    ctx = RepoContext(repo)
    selected = select_checks(only)
    visibility = ctx.visibility  # GhError propagates to the caller

    if any("clone" in c.needs for c in selected):
        ctx.ensure_workdir()

    from .captain import fleet_lock_rows

    rows = []
    rows.extend(fleet_lock_rows(ctx))
    unknown = ctx.config.unknown_keys(set(CHECKS))
    if unknown:
        rows.append(
            {
                "check": "config",
                "status": Status.FAIL.value,
                "severity": "required",
                "details": f"unknown keys in .housekeeping.toml: {', '.join(unknown)}",
                "note": "a typo, or config from a newer housekeeping — nothing reads these",
                "fixable": False,
            }
        )
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    for check in selected:
        severity = ctx.config.severity(check.name, visibility)
        if severity == "off":
            continue
        severity, demoted = effective_severity(check.name, severity, event)
        try:
            result = check.run(ctx)
        except Exception as e:  # a broken check shouldn't sink the run
            result = Result(Status.ERROR, f"check crashed: {e}")
        note = result.note
        if demoted and result.status == Status.FAIL:
            suffix = "informational on PR runs — grades main/settings, which a PR can't change"
            note = f"{note}; {suffix}" if note else suffix
        rows.append(
            {
                "check": check.name,
                "status": result.status.value,
                "severity": severity,
                "details": result.details,
                "note": note,
                "fixable": check.fixable,
            }
        )

    from .ci_versions import ci_versions, read_workflows

    payload = {
        "repo": repo,
        "visibility": visibility,
        "logo": ctx.config.logo,
        "ci_versions": ci_versions(repo, read_workflows(getattr(ctx, "workdir", None))),
        "activity": fetch_activity(ctx),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": rows,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / f"{repo.replace('/', '--')}.json"
    results_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def audit_fleet(members: list, max_workers: int = 8) -> list[dict | None]:
    """Audit every member concurrently, returning payloads in member order.
    An unreachable member (GhError) becomes None rather than sinking the run.

    Members are independent — each hits its own repo via `gh`/`git` and writes its
    own results file — so they parallelize cleanly; wall-clock drops to about the
    slowest single repo instead of the sum."""

    def one(member) -> dict | None:
        try:
            return audit(member.repo)
        except GhError as e:
            console.print(f"[red]{member.repo}: api error: {e}[/red]")
            return None

    if not members:
        return []
    console.print(f"[dim]auditing {len(members)} members concurrently…[/dim]")
    with ThreadPoolExecutor(max_workers=min(max_workers, len(members))) as pool:
        return list(pool.map(one, members))  # map preserves input order


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
        console.print(
            f"[dim]results saved to {RESULTS_DIR / (repo.replace('/', '--') + '.json')}[/dim]"
        )

    # Inside GitHub Actions, also render into the job summary.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as summary:
            summary.write(render_markdown(payload) + "\n")

    return exit_code(payload)


def _detection_payload(workdir: Path) -> dict:
    """Pure detection over a working copy — what the repo contains and produces."""
    ecosystems = detect_ecosystems(workdir)
    artifacts = detect_artifacts(workdir)
    return {
        "ecosystems": [
            {
                "name": e.name,
                "dir": e.dir,
                "language": e.language,
                "lockfile": e.lockfile,
                "recommends": list(e.recommends),
            }
            for e in ecosystems
        ],
        "typed_languages": detect_typed_languages(workdir),
        "artifacts": [
            {
                "name": a.name,
                "label": a.label,
                "heavy": a.heavy,
                "guidance": a.guidance,
            }
            for a in artifacts
        ],
    }


def detect_payload(repo: str) -> dict:
    ctx = RepoContext(repo)
    ctx.ensure_workdir()
    return {"repo": repo, **_detection_payload(ctx.workdir)}


def render_detect(payload: dict) -> None:
    console.print(f"[bold]{payload['repo']}[/bold]")
    ecos = payload["ecosystems"]
    console.print(
        "\n[bold]Ecosystems[/bold]: "
        + (
            ", ".join(
                f"{e['name']}"
                + (f" ({e['dir']})" if e.get("dir") else "")
                + (f" [{e['language']}]" if e["language"] else "")
                + (f" -> {e['lockfile']}" if e["lockfile"] else "")
                for e in ecos
            )
            or "none detected"
        )
    )
    typed = payload["typed_languages"]
    console.print(
        "[bold]Typed languages[/bold]: " + (", ".join(typed) or "none detected")
    )
    arts = payload["artifacts"]
    console.print(
        "[bold]Artifacts[/bold]: "
        + (
            ", ".join(a["label"] + (" [heavy]" if a["heavy"] else "") for a in arts)
            or "none detected"
        )
    )
    recommends = [(e["name"], e["recommends"]) for e in ecos if e["recommends"]]
    if recommends:
        console.print("\n[bold]Recommended fleet setup[/bold]:")
        for name, items in recommends:
            console.print(f"  [cyan]{name}[/cyan]")
            for item in items:
                console.print(f"    - {item}")


def cmd_detect(args) -> int:
    repo = resolve_repo(args.repo)
    try:
        payload = detect_payload(repo)
    except GhError as e:
        console.print(f"[red]cannot reach {repo}:[/red] {e}")
        return 2
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        render_detect(payload)
    return 0


def cmd_fix(args) -> int:
    repo = resolve_repo(args.repo)
    if args.check not in CHECKS:
        console.print(
            f"[red]unknown check {args.check!r}[/red] (available: {', '.join(CHECKS)})"
        )
        return 2
    check = CHECKS[args.check]
    if check.fix is None:
        console.print(
            f"[yellow]{check.name} has no automated fix[/yellow] — see the check details for what to do"
        )
        return 2

    ctx = RepoContext(repo)
    if "clone" in check.needs:
        ctx.ensure_workdir()
    result = check.run(ctx)
    if result.status == Status.PASS:
        console.print(f"[green]{check.name} already passes[/green] — nothing to fix")
        return 0
    if result.status == Status.SKIP:
        console.print(
            f"[dim]{check.name} is skipped for this repo:[/dim] {result.details}"
        )
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
        console.print(
            f"[red]no manifest at {path}[/red] — pass a housecaptain.toml path"
        )
        sys.exit(2)
    return load_manifest(path)


CAPTAIN_STYLE = {
    "ok": ("✓", "green"),
    "fail": ("✗", "red"),
    "conflict": ("≠", "yellow"),
    "error": ("!", "yellow"),
    "parked": ("–", "dim"),
}


def cmd_captain(args) -> int:
    from .captain import MemberReport, captain_member, dispatch_self_audit

    manifest = load_manifest_or_exit(args.manifest)
    manifest_dir = Path(args.manifest or "housecaptain.toml").parent
    bad_policy = bool(manifest.unknown_policy)
    if bad_policy:
        console.print(
            f"[red]unknown policy keys in the manifest: "
            f"{', '.join(manifest.unknown_policy)}[/red] — a typo, or policy "
            "from a newer housekeeping than this captain; fix one of the two"
        )

    reports = []
    contexts: dict[str, RepoContext] = {}
    for member in manifest.members:
        if member.parked:
            reports.append(
                MemberReport(
                    member.repo,
                    "parked",
                    "in the fleet, not yet expected to self-audit",
                    note=member.note,
                )
            )
            continue
        contexts[member.repo] = ctx = RepoContext(member.repo)
        try:
            report = captain_member(
                ctx,
                manifest.policy_checks,
                manifest.required_files,
                manifest.locked,
                manifest.captain,
                manifest.managed_configs,
                manifest_dir,
            )
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
    lines = [
        f"### {manifest.name} fleet",
        "",
        "| member | status | details | note |",
        "|---|---|---|---|",
    ]
    for report in reports:
        symbol, style = CAPTAIN_STYLE[report.status]
        table.add_row(
            report.repo,
            f"[{style}]{symbol} {report.status}[/{style}]",
            escape(report.details),
            escape(report.note),
        )
        cells = [report.repo, f"{symbol} {report.status}", report.details, report.note]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    console.print(table)

    if getattr(args, "dispatch", False):
        for report in reports:
            if report.status == "parked" or not report.workflow_path:
                continue
            outcome = dispatch_self_audit(contexts[report.repo], report.workflow_path)
            console.print(f"[dim]{report.repo}: {outcome}[/dim]")
            lines.append(f"\ndispatch {report.repo}: {outcome}")

    if getattr(args, "sync_configs", False):
        from .captain import sync_configs
        from .fixing import confirm

        # In Actions there's no TTY to confirm at; the workflow opts in via --yes.
        assume_yes = args.yes or os.environ.get("GITHUB_ACTIONS") == "true"
        for repo, check, outcome in sync_configs(
            manifest, manifest_dir, assume_yes, confirm
        ):
            console.print(f"[dim]sync {repo} {check}: {outcome}[/dim]")
            lines.append(f"\nsync {repo} {check}: {outcome}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as summary:
            summary.write("\n".join(lines) + "\n")

    failing = any(r.status in ("fail", "conflict", "error") for r in reports)
    return 1 if failing or bad_policy else 0


def cmd_fleet(args) -> int:
    manifest = load_manifest_or_exit(args.manifest)
    payloads = audit_fleet(manifest.members)

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
        table.add_row(
            member.repo,
            str(passed),
            str(len(warns)),
            str(len(hard)),
            ", ".join(r["check"] for r in hard) or "-",
        )
        if hard:
            worst = 1
    console.print(table)
    console.print("[dim]per-repo detail: housekeeper report <owner/repo>[/dim]")

    if getattr(args, "html", None):
        from .dashboard import render_document

        Path(args.html).write_text(
            render_document(manifest.name, manifest.members, payloads)
        )
        console.print(f"[green]dashboard written to {args.html}[/green]")
    return worst


def cmd_serve(args) -> int:
    manifest = load_manifest_or_exit(args.manifest)
    from .dashboard import render_document
    from .serve import serve

    def generate() -> str:
        payloads = audit_fleet(manifest.members)
        return render_document(manifest.name, manifest.members, payloads)

    return serve(
        generate, host=args.host, port=args.port, open_browser=not args.no_open
    )


def render_scaffold(result) -> None:
    console.print(f"\n[bold]{result.dest}[/bold] ({result.flavor} skeleton)")
    if result.created:
        console.print(f"\n[green]created {len(result.created)} file(s):[/green]")
        for rel in result.created:
            console.print(f"  [green]+[/green] {rel}")
    if result.skipped:
        console.print(
            f"\n[yellow]skipped {len(result.skipped)} existing file(s)[/yellow] "
            "(pass --force to overwrite):"
        )
        for rel in result.skipped:
            console.print(f"  [dim]= {rel}[/dim]")
    console.print("\n[bold]Next steps (can't be scaffolded):[/bold]")
    for step in result.next_steps:
        console.print(f"  [cyan]-[/cyan] {step}")


def cmd_new(args) -> int:
    from .scaffold import FLAVORS, scaffold

    if args.flavor not in FLAVORS:
        console.print(
            f"[red]unknown flavor {args.flavor!r}[/red] "
            f"(choose one of: {', '.join(sorted(FLAVORS))})"
        )
        return 2
    dest = Path(args.dir).expanduser() / args.name
    result = scaffold(
        dest,
        args.name,
        args.flavor,
        args.private,
        args.force,
        args.dependabot_automerge,
    )
    render_scaffold(result)
    return 0


def cmd_report(args) -> int:
    repo = resolve_repo(args.repo)
    results_path = RESULTS_DIR / f"{repo.replace('/', '--')}.json"
    if not results_path.is_file():
        console.print(
            f"[red]no saved results for {repo}[/red] — run `housekeeper check` first"
        )
        return 2
    payload = json.loads(results_path.read_text())
    render(payload)
    return exit_code(payload)


def render(payload: dict) -> None:
    table = Table(
        title=f"{payload['repo']} ({payload['visibility']}) — {payload['checked_at']}"
    )
    table.add_column("check")
    table.add_column("status")
    table.add_column("details", overflow="fold")
    table.add_column("note", style="dim", overflow="fold")
    for row in payload["results"]:
        symbol, style = STYLE[Status(row["status"])]
        status = f"[{style}]{symbol} {row['status']}[/{style}]"
        if row["status"] == "fail" and row["severity"] == "recommended":
            status = "[yellow]! warn[/yellow]"
        # escape() so literal brackets in check output ("[[codegen]]") aren't
        # eaten as rich markup
        details = escape(row["details"])
        if row["status"] == "fail" and row["fixable"]:
            details += f"  [cyan](housekeeper fix {row['check']})[/cyan]"
        table.add_row(row["check"], status, details, escape(row["note"]))
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
    bad = [
        r
        for r in payload["results"]
        if r["status"] in ("fail", "error") and r["severity"] == "required"
    ]
    return 1 if bad else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="housekeeper", description="Check that a GitHub repo is in good order."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="run checks (read-only)")
    p_check.add_argument(
        "repo", nargs="?", help="owner/repo (default: inferred from cwd)"
    )
    p_check.add_argument("--only", help="comma-separated check names")
    p_check.add_argument("--json", action="store_true", help="print results as JSON")
    p_check.set_defaults(func=cmd_check)

    p_fix = sub.add_parser(
        "fix", help="fix one failing check (asks before changing anything)"
    )
    p_fix.add_argument("check", help="check name to fix")
    p_fix.add_argument(
        "repo", nargs="?", help="owner/repo (default: inferred from cwd)"
    )
    p_fix.set_defaults(func=cmd_fix)

    p_new = sub.add_parser("new", help="scaffold a new fleet-compliant repo skeleton")
    p_new.add_argument("name", help="repo name (also the new directory name)")
    p_new.add_argument(
        "--dir",
        default=".",
        help="parent directory to create the repo in (default: current directory)",
    )
    p_new.add_argument(
        "--flavor",
        default="python",
        choices=["rust", "bun", "python"],
        help="ecosystem skeleton to scaffold (default: python)",
    )
    p_new.add_argument(
        "--private",
        action="store_true",
        help="soften audience-facing expectations in the generated config",
    )
    p_new.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing files instead of skipping them",
    )
    p_new.add_argument(
        "--dependabot-automerge",
        action="store_true",
        dest="dependabot_automerge",
        help="opt into dependabot auto-merge: add the workflow and the "
        "[allow-auto-merge] config (default off)",
    )
    p_new.set_defaults(func=cmd_new)

    p_report = sub.add_parser("report", help="re-render the last check run")
    p_report.add_argument(
        "repo", nargs="?", help="owner/repo (default: inferred from cwd)"
    )
    p_report.set_defaults(func=cmd_report)

    p_detect = sub.add_parser(
        "detect",
        help="show detected ecosystems, artifacts, and the recommended setup",
    )
    p_detect.add_argument(
        "repo", nargs="?", help="owner/repo (default: inferred from cwd)"
    )
    p_detect.add_argument("--json", action="store_true", help="print detection as JSON")
    p_detect.set_defaults(func=cmd_detect)

    p_captain = sub.add_parser(
        "captain", help="check every fleet member is auditing itself (API-only)"
    )
    p_captain.add_argument("manifest", nargs="?", help="path to housecaptain.toml")
    p_captain.add_argument(
        "--dispatch",
        action="store_true",
        help="also trigger every member's self-audit now",
    )
    p_captain.add_argument(
        "--sync-configs",
        action="store_true",
        dest="sync_configs",
        help="push fleet-owned managed configs to members as isolated PRs",
    )
    p_captain.add_argument(
        "--yes",
        action="store_true",
        help="skip the per-member confirmation on --sync-configs (for CI)",
    )
    p_captain.set_defaults(func=cmd_captain)

    p_fleet = sub.add_parser("fleet", help="full local audit of every fleet member")
    p_fleet.add_argument("manifest", nargs="?", help="path to housecaptain.toml")
    p_fleet.add_argument(
        "--html", metavar="FILE", help="also write an HTML check matrix dashboard"
    )
    p_fleet.set_defaults(func=cmd_fleet)

    p_serve = sub.add_parser(
        "serve", help="serve the fleet dashboard with a live Regenerate button"
    )
    p_serve.add_argument("manifest", nargs="?", help="path to housecaptain.toml")
    p_serve.add_argument(
        "--port", type=int, default=8799, help="port to listen on (default: 8799)"
    )
    p_serve.add_argument(
        "--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)"
    )
    p_serve.add_argument(
        "--no-open",
        action="store_true",
        dest="no_open",
        help="don't open a browser on start",
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))

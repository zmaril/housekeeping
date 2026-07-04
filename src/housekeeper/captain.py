"""Fleet captain: repos audit themselves; the captain checks the auditors.

The manifest (housecaptain.toml) lives in the captain repo and names the
fleet. `housekeeper captain` is the shallow delegation check that runs in the
captain's CI — per member, API-only: a housekeeping workflow exists, fires on
pull_request + push + schedule, its latest default-branch run is green, and
the member's .housekeeping.toml doesn't contradict fleet policy. Policy
divergence is SURFACED, never silently resolved in either direction.

`housekeeper fleet` is the deep local audit: the full check suite against
every member from your machine.
"""

from __future__ import annotations

import base64
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .context import RepoContext
from .checks.ci import triggers as workflow_triggers

REQUIRED_TRIGGERS = {"pull_request", "push", "schedule", "workflow_dispatch"}
KNOWN_POLICY = {"checks", "required-file"}


def is_housekeeping_workflow(repo: str, text: str) -> bool:
    # A captain workflow also uses the action, but it audits the fleet,
    # not this repo — don't mistake it for the self-audit.
    if "captain:" in text:
        return False
    if "housekeeping@" in text:
        return True
    # housekeeping's own repo runs the action as `uses: ./`
    return repo.split("/")[-1].lower() == "housekeeping" and "uses: ./" in text


@dataclass
class Member:
    repo: str
    note: str = ""
    parked: bool = False  # listed but not yet expected to self-audit; never fails the captain


@dataclass
class RequiredFile:
    path: str
    scope: str = "all"  # all | public | private


@dataclass
class Manifest:
    name: str
    members: list[Member]
    policy_checks: dict[str, str] = field(default_factory=dict)
    required_files: list[RequiredFile] = field(default_factory=list)
    unknown_policy: list[str] = field(default_factory=list)


def load_manifest(path: Path) -> Manifest:
    data = tomllib.loads(path.read_text())
    members = [Member(repo=m["repo"], note=m.get("note", ""),
                      parked=bool(m.get("parked", False)))
               for m in data.get("member", [])]
    if not members:
        raise ValueError(f"{path}: no [[member]] entries")
    policy = data.get("policy", {})
    required = [RequiredFile(path=f["path"], scope=f.get("scope", "all"))
                for f in policy.get("required-file", [])]
    for rf in required:
        if rf.scope not in ("all", "public", "private"):
            raise ValueError(f"{path}: required-file scope {rf.scope!r} "
                             "must be all, public, or private")
    return Manifest(
        name=data.get("name", path.stem),
        members=members,
        policy_checks=policy.get("checks", {}),
        required_files=required,
        # Surfaced, never silently ignored: a typo'd policy section (or one
        # from a newer housekeeping) should be seen, not skipped.
        unknown_policy=sorted(set(policy) - KNOWN_POLICY),
    )


@dataclass
class MemberReport:
    repo: str
    status: str  # "ok" | "fail" | "conflict" | "error" | "parked"
    details: str
    note: str = ""
    workflow_path: str = ""


def _file_text(ctx: RepoContext, path: str) -> str | None:
    blob = ctx.try_api(f"repos/{ctx.repo}/contents/{path}")
    if not isinstance(blob, dict) or blob.get("encoding") != "base64":
        return None
    return base64.b64decode(blob["content"]).decode(errors="replace")


def find_housekeeping_workflow(ctx: RepoContext) -> tuple[str, set[str]] | None:
    """Return (workflow path, triggers) of the member's housekeeping workflow."""
    listing = ctx.try_api(f"repos/{ctx.repo}/contents/.github/workflows") or []
    for entry in listing:
        if not (isinstance(entry, dict) and entry.get("name", "").endswith((".yml", ".yaml"))):
            continue
        text = _file_text(ctx, entry["path"])
        if not text or not is_housekeeping_workflow(ctx.repo, text):
            continue
        try:
            parsed = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            return entry["path"], set()
        return entry["path"], workflow_triggers(parsed)
    return None


def latest_run_conclusion(ctx: RepoContext, workflow_path: str) -> tuple[str, str]:
    """(conclusion, url) of the workflow's latest completed default-branch run."""
    workflows = ctx.api(f"repos/{ctx.repo}/actions/workflows").get("workflows", [])
    match = next((w for w in workflows if w.get("path") == workflow_path), None)
    if match is None:
        return "no-runs", ""
    runs = ctx.api(f"repos/{ctx.repo}/actions/workflows/{match['id']}/runs",
                   params={"branch": ctx.default_branch, "status": "completed",
                           "per_page": 1})
    latest = (runs.get("workflow_runs") or [None])[0]
    if latest is None:
        return "no-runs", ""
    return latest.get("conclusion") or "unknown", latest.get("html_url", "")


def policy_conflicts(ctx: RepoContext, policy: dict[str, str]) -> list[str]:
    """Fleet policy vs the member's own .housekeeping.toml. Same value or
    member silence is fine; a differing value is a conflict to surface."""
    if not policy:
        return []
    text = _file_text(ctx, ".housekeeping.toml")
    if text is None:
        return []
    try:
        member_checks = tomllib.loads(text).get("checks", {})
    except tomllib.TOMLDecodeError:
        return [".housekeeping.toml does not parse"]
    return [
        f"{check}: member says {member_checks[check]!r}, fleet policy says {value!r}"
        for check, value in sorted(policy.items())
        if check in member_checks and member_checks[check] != value
    ]


def captain_member(ctx: RepoContext, policy: dict[str, str],
                   required_files: list[RequiredFile] | None = None) -> MemberReport:
    found = find_housekeeping_workflow(ctx)
    if found is None:
        return MemberReport(ctx.repo, "fail",
                            "no housekeeping workflow — this repo isn't auditing itself")
    workflow_path, trigger_set = found

    problems = []
    missing = REQUIRED_TRIGGERS - trigger_set
    if missing:
        problems.append(f"workflow missing triggers: {', '.join(sorted(missing))}")

    for required in required_files or []:
        if required.scope != "all" and ctx.visibility != required.scope:
            continue
        if ctx.try_api(f"repos/{ctx.repo}/contents/{required.path}") is None:
            problems.append(f"missing {required.path} "
                            f"(fleet policy for {required.scope} repos)")

    conclusion, url = latest_run_conclusion(ctx, workflow_path)
    if conclusion == "no-runs":
        problems.append("no completed default-branch runs yet")
    elif conclusion != "success":
        problems.append(f"latest self-audit run: {conclusion} ({url})")

    conflicts = policy_conflicts(ctx, policy)
    if conflicts:
        return MemberReport(ctx.repo, "conflict",
                            "; ".join(conflicts),
                            note="; ".join(problems) if problems else
                            "reconcile the member's .housekeeping.toml with fleet policy",
                            workflow_path=workflow_path)
    if problems:
        return MemberReport(ctx.repo, "fail", "; ".join(problems),
                            workflow_path=workflow_path)
    return MemberReport(ctx.repo, "ok",
                        f"self-auditing via {workflow_path}, latest run green",
                        workflow_path=workflow_path)


def dispatch_self_audit(ctx: RepoContext, workflow_path: str) -> str:
    """Trigger a member's self-audit now — the fleet's 'now' button, so new
    checks don't wait a week of crons to reach everyone."""
    from .context import GhError

    workflows = ctx.api(f"repos/{ctx.repo}/actions/workflows").get("workflows", [])
    match = next((w for w in workflows if w.get("path") == workflow_path), None)
    if match is None:
        return "workflow not found"
    try:
        ctx.api(f"repos/{ctx.repo}/actions/workflows/{match['id']}/dispatches",
                method="POST", input={"ref": ctx.default_branch})
    except GhError as e:
        if e.status == 422:
            return "not dispatchable — workflow lacks the workflow_dispatch trigger"
        if e.status == 403:
            return "token can't dispatch here (needs actions: write)"
        raise
    return "dispatched"

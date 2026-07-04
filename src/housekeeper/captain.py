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

REQUIRED_TRIGGERS = {"pull_request", "push", "schedule"}


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
class Manifest:
    name: str
    members: list[Member]
    policy_checks: dict[str, str] = field(default_factory=dict)


def load_manifest(path: Path) -> Manifest:
    data = tomllib.loads(path.read_text())
    members = [Member(repo=m["repo"], note=m.get("note", ""),
                      parked=bool(m.get("parked", False)))
               for m in data.get("member", [])]
    if not members:
        raise ValueError(f"{path}: no [[member]] entries")
    return Manifest(
        name=data.get("name", path.stem),
        members=members,
        policy_checks=data.get("policy", {}).get("checks", {}),
    )


@dataclass
class MemberReport:
    repo: str
    status: str  # "ok" | "fail" | "conflict" | "error"
    details: str
    note: str = ""


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


def captain_member(ctx: RepoContext, policy: dict[str, str]) -> MemberReport:
    found = find_housekeeping_workflow(ctx)
    if found is None:
        return MemberReport(ctx.repo, "fail",
                            "no housekeeping workflow — this repo isn't auditing itself")
    workflow_path, trigger_set = found

    problems = []
    missing = REQUIRED_TRIGGERS - trigger_set
    if missing:
        problems.append(f"workflow missing triggers: {', '.join(sorted(missing))}")

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
                            "reconcile the member's .housekeeping.toml with fleet policy")
    if problems:
        return MemberReport(ctx.repo, "fail", "; ".join(problems))
    return MemberReport(ctx.repo, "ok",
                        f"self-auditing via {workflow_path}, latest run green")

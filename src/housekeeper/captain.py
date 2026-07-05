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
KNOWN_POLICY = {"checks", "required-file", "locked", "managed-config"}

# Canonical fleet configs live here in the captain repo; the sync workflow's
# path filter keys off this prefix, so load_manifest holds every source to it.
FLEET_DIR = ".fleet"

# Where a member's incoming config-sync PR lands. One branch per managed check,
# reused across syncs so the PR updates in place rather than piling up.
FLEET_CONFIG_BRANCH = "housekeeping/fleet-config-{check}"


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
    parked: bool = (
        False  # listed but not yet expected to self-audit; never fails the captain
    )


@dataclass
class RequiredFile:
    path: str
    scope: str = "all"  # all | public | private


@dataclass
class ManagedConfig:
    """A config the captain owns and pushes to the fleet. `paths` maps each
    member destination to its canonical source under .fleet/ in the captain
    repo. A trailing-slash destination is a directory sync (e.g. vale's vocab);
    a plain one is a single file."""

    check: str
    paths: dict[str, str]  # member destination -> captain source (under .fleet/)
    scope: str = "all"  # all | public | private


@dataclass
class Manifest:
    name: str
    members: list[Member]
    policy_checks: dict[str, str] = field(default_factory=dict)
    required_files: list[RequiredFile] = field(default_factory=list)
    managed_configs: list[ManagedConfig] = field(default_factory=list)
    unknown_policy: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)  # dotted keys members may not set
    captain: str = ""  # owner/repo of the captain itself; members declare fleet = this


def _parse_managed_config(path: Path, mc: dict) -> ManagedConfig:
    check = mc.get("check")
    if not check:
        raise ValueError(f"{path}: every [[policy.managed-config]] needs a check =")
    paths = mc.get("paths", {})
    if not isinstance(paths, dict) or not paths:
        raise ValueError(
            f"{path}: managed-config for {check!r} needs a non-empty "
            "paths = {{ member = source }} table"
        )
    for source in paths.values():
        norm = source.rstrip("/")
        if norm != FLEET_DIR and not norm.startswith(FLEET_DIR + "/"):
            raise ValueError(
                f"{path}: managed-config source {source!r} must live under "
                f"{FLEET_DIR}/ (so the sync workflow's path filter catches it)"
            )
    scope = mc.get("scope", "all")
    if scope not in ("all", "public", "private"):
        raise ValueError(
            f"{path}: managed-config scope {scope!r} must be all, public, or private"
        )
    return ManagedConfig(check=check, paths=dict(paths), scope=scope)


def load_manifest(path: Path) -> Manifest:
    data = tomllib.loads(path.read_text())
    members = [
        Member(
            repo=m["repo"], note=m.get("note", ""), parked=bool(m.get("parked", False))
        )
        for m in data.get("member", [])
    ]
    if not members:
        raise ValueError(f"{path}: no [[member]] entries")
    policy = data.get("policy", {})
    required = [
        RequiredFile(path=f["path"], scope=f.get("scope", "all"))
        for f in policy.get("required-file", [])
    ]
    for rf in required:
        if rf.scope not in ("all", "public", "private"):
            raise ValueError(
                f"{path}: required-file scope {rf.scope!r} "
                "must be all, public, or private"
            )
    managed = [
        _parse_managed_config(path, mc) for mc in policy.get("managed-config", [])
    ]
    locked = list(policy.get("locked", []))
    if locked and not data.get("captain"):
        raise ValueError(
            f"{path}: [policy] locked requires a top-level "
            'captain = "owner/repo" so members can declare their fleet'
        )
    return Manifest(
        name=data.get("name", path.stem),
        members=members,
        policy_checks=policy.get("checks", {}),
        required_files=required,
        managed_configs=managed,
        # Surfaced, never silently ignored: a typo'd policy section (or one
        # from a newer housekeeping) should be seen, not skipped.
        unknown_policy=sorted(set(policy) - KNOWN_POLICY),
        locked=locked,
        captain=data.get("captain", ""),
    )


def lock_violations(member_config: dict, locked: list[str]) -> list[str]:
    """Locked keys the member's .housekeeping.toml sets anyway."""
    violations = []
    for key in locked:
        section, _, leaf = key.partition(".")
        table = member_config.get(section, {})
        if isinstance(table, dict) and leaf in table:
            violations.append(key)
    return violations


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
        if not (
            isinstance(entry, dict)
            and entry.get("name", "").endswith((".yml", ".yaml"))
        ):
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
    runs = ctx.api(
        f"repos/{ctx.repo}/actions/workflows/{match['id']}/runs",
        params={"branch": ctx.default_branch, "status": "completed", "per_page": 1},
    )
    latest = (runs.get("workflow_runs") or [None])[0]
    if latest is None:
        return "no-runs", ""
    return latest.get("conclusion") or "unknown", latest.get("html_url", "")


def member_config(ctx: RepoContext) -> dict | None:
    """The member's parsed .housekeeping.toml; None if absent, {} if unparseable."""
    text = _file_text(ctx, ".housekeeping.toml")
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def policy_conflicts(
    ctx: RepoContext,
    policy: dict[str, str],
    locked: list[str] | None = None,
    captain_repo: str = "",
) -> list[str]:
    """Fleet policy vs the member's own .housekeeping.toml. Same value or
    member silence is fine; a differing value is a conflict to surface.
    Locked keys are stricter: setting one at all is a conflict, and when
    locks exist the member must declare its fleet so its OWN audits enforce
    them at PR time (the captain is only the backstop)."""
    config = member_config(ctx)
    conflicts = []
    if config is not None:
        member_checks = config.get("checks", {})
        conflicts += [
            f"{check}: member says {member_checks[check]!r}, fleet policy says {value!r}"
            for check, value in sorted(policy.items())
            if check in member_checks and member_checks[check] != value
        ]
    if locked:
        conflicts += [
            f"{key} is locked by fleet policy but set locally"
            for key in lock_violations(config or {}, locked)
        ]
        declared = (config or {}).get("fleet", "")
        if declared != captain_repo:
            conflicts.append(
                f'member must declare fleet = "{captain_repo}" in '
                ".housekeeping.toml — without it, locks aren't "
                "enforced on the member's own PRs"
            )
    return conflicts


def expand_managed_config(manifest_dir: Path, mc: ManagedConfig) -> dict[str, str]:
    """Flatten a managed-config's .fleet/ sources into the concrete
    {member_destination: content} a member should carry. Trailing-slash
    destinations expand to every file beneath the captain source directory."""
    desired: dict[str, str] = {}
    for member_path, source in mc.paths.items():
        src = manifest_dir / source
        if member_path.endswith("/"):
            if not src.is_dir():
                raise ValueError(
                    f"managed-config {mc.check}: {source} is not a directory "
                    "in the captain repo"
                )
            for file in sorted(src.rglob("*")):
                if file.is_file():
                    desired[member_path + file.relative_to(src).as_posix()] = (
                        file.read_text()
                    )
        else:
            if not src.is_file():
                raise ValueError(
                    f"managed-config {mc.check}: {source} not found in the captain repo"
                )
            desired[member_path] = src.read_text()
    return desired


def member_drift(ctx: RepoContext, desired: dict[str, str]) -> list[str]:
    """Member destinations whose current content differs from (or is missing
    against) fleet canonical."""
    return [dest for dest, want in desired.items() if _file_text(ctx, dest) != want]


def managed_config_notes(
    ctx: RepoContext,
    managed_configs: list[ManagedConfig] | None,
    manifest_dir: Path | None,
) -> list[str]:
    """Per in-scope managed-config, a human status line when the member's copy
    lags fleet canonical. Informational only — drift never fails a member (they
    adopt the sync PR at their own pace), so it colours the note, not the
    status."""
    if not managed_configs or manifest_dir is None:
        return []
    notes = []
    for mc in managed_configs:
        if mc.scope != "all" and ctx.visibility != mc.scope:
            continue
        if not member_drift(ctx, expand_managed_config(manifest_dir, mc)):
            continue
        branch = FLEET_CONFIG_BRANCH.format(check=mc.check)
        open_pr = ctx.try_api(f"repos/{ctx.repo}/branches/{branch}") is not None
        state = "sync PR open" if open_pr else "stale — will open a sync PR"
        notes.append(f"{mc.check} config drifts from fleet ({state})")
    return notes


def captain_member(
    ctx: RepoContext,
    policy: dict[str, str],
    required_files: list[RequiredFile] | None = None,
    locked: list[str] | None = None,
    captain_repo: str = "",
    managed_configs: list[ManagedConfig] | None = None,
    manifest_dir: Path | None = None,
) -> MemberReport:
    managed_note = "; ".join(managed_config_notes(ctx, managed_configs, manifest_dir))

    def finish(report: MemberReport) -> MemberReport:
        if managed_note:
            report.note = f"{report.note}; {managed_note}" if report.note else managed_note
        return report

    found = find_housekeeping_workflow(ctx)
    if found is None:
        return finish(
            MemberReport(
                ctx.repo,
                "fail",
                "no housekeeping workflow — this repo isn't auditing itself",
            )
        )
    workflow_path, trigger_set = found

    problems = []
    missing = REQUIRED_TRIGGERS - trigger_set
    if missing:
        problems.append(f"workflow missing triggers: {', '.join(sorted(missing))}")

    for required in required_files or []:
        if required.scope != "all" and ctx.visibility != required.scope:
            continue
        if ctx.try_api(f"repos/{ctx.repo}/contents/{required.path}") is None:
            problems.append(
                f"missing {required.path} (fleet policy for {required.scope} repos)"
            )

    conclusion, url = latest_run_conclusion(ctx, workflow_path)
    if conclusion == "no-runs":
        problems.append("no completed default-branch runs yet")
    elif conclusion != "success":
        problems.append(f"latest self-audit run: {conclusion} ({url})")

    conflicts = policy_conflicts(ctx, policy, locked, captain_repo)
    if conflicts:
        return finish(
            MemberReport(
                ctx.repo,
                "conflict",
                "; ".join(conflicts),
                note="; ".join(problems)
                if problems
                else "reconcile the member's .housekeeping.toml with fleet policy",
                workflow_path=workflow_path,
            )
        )
    if problems:
        return finish(
            MemberReport(
                ctx.repo, "fail", "; ".join(problems), workflow_path=workflow_path
            )
        )
    return finish(
        MemberReport(
            ctx.repo,
            "ok",
            f"self-auditing via {workflow_path}, latest run green",
            workflow_path=workflow_path,
        )
    )


def _head_tree(ctx: RepoContext) -> tuple[str, str]:
    """(commit sha, tree sha) of the member's default-branch tip."""
    ref = ctx.api(f"repos/{ctx.repo}/git/ref/heads/{ctx.default_branch}")
    head_sha = ref["object"]["sha"]
    commit = ctx.api(f"repos/{ctx.repo}/git/commits/{head_sha}")
    return head_sha, commit["tree"]["sha"]


def _branch_tree(ctx: RepoContext, branch: str) -> str | None:
    """Tree sha of a branch's tip, or None if the branch doesn't exist."""
    ref = ctx.try_api(
        f"repos/{ctx.repo}/git/ref/heads/{branch}", none_on=(404, 422)
    )
    if not ref:
        return None
    commit = ctx.api(f"repos/{ctx.repo}/git/commits/{ref['object']['sha']}")
    return commit["tree"]["sha"]


def sync_member_config(
    ctx: RepoContext,
    check: str,
    desired: dict[str, str],
    assume_yes: bool = False,
    confirm_fn=None,
) -> str:
    """Bring one member's copy of a managed config in line with fleet canonical
    by opening (or updating) an isolated PR. Read-only when already in sync.

    The commit is crafted through the git-data API (tree → commit → ref) so a
    fan-out needs no clones, and the branch is always rebuilt on the current
    default-branch tree — the PR stays a minimal, config-only diff. Nothing is
    pushed when the resulting tree already matches the open sync branch, so
    reruns don't churn."""
    branch = FLEET_CONFIG_BRANCH.format(check=check)
    branch_tree = _branch_tree(ctx, branch)
    if branch_tree is None and not member_drift(ctx, desired):
        return "in sync"

    head_sha, base_tree = _head_tree(ctx)
    entries = [
        {"path": path, "mode": "100644", "type": "blob", "content": content}
        for path, content in sorted(desired.items())
    ]
    new_tree = ctx.api(
        f"repos/{ctx.repo}/git/trees",
        method="POST",
        input={"base_tree": base_tree, "tree": entries},
    )["sha"]
    if branch_tree == new_tree:
        return "sync PR already up to date"

    if not assume_yes and not (
        confirm_fn and confirm_fn(f"Open/update {check} config PR on {ctx.repo}?")
    ):
        return "skipped"

    title = f"chore(config): sync {check} config from fleet"
    commit_sha = ctx.api(
        f"repos/{ctx.repo}/git/commits",
        method="POST",
        input={"message": title, "tree": new_tree, "parents": [head_sha]},
    )["sha"]
    if branch_tree is None:
        ctx.api(
            f"repos/{ctx.repo}/git/refs",
            method="POST",
            input={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
    else:
        # Force so the branch tracks the latest default-branch tree even when
        # main moved under an already-open PR.
        ctx.api(
            f"repos/{ctx.repo}/git/refs/heads/{branch}",
            method="PATCH",
            input={"sha": commit_sha, "force": True},
        )

    owner = ctx.repo.split("/")[0]
    if ctx.api(f"repos/{ctx.repo}/pulls?head={owner}:{branch}&state=open"):
        return "sync PR updated"
    body = (
        f"Centralized **{check}** config update from the fleet captain.\n\n"
        "Adopt at your own pace. Merging may surface new lint findings — "
        "cleaning those up stays this repo's own call, one repo at a time. "
        "The captain never touches your code, only this config.\n\n"
        "_Opened automatically by `housekeeper captain --sync-configs`._"
    )
    ctx.api(
        f"repos/{ctx.repo}/pulls",
        method="POST",
        input={"title": title, "head": branch, "base": ctx.default_branch, "body": body},
    )
    return "sync PR opened"


def sync_configs(
    manifest: Manifest,
    manifest_dir: Path,
    assume_yes: bool = False,
    confirm_fn=None,
) -> list[tuple[str, str, str]]:
    """Push every managed config to every in-scope member. Returns
    (repo, check, outcome) rows for reporting."""
    from .context import GhError

    results = []
    for member in manifest.members:
        if member.parked:
            continue
        ctx = RepoContext(member.repo)
        for mc in manifest.managed_configs:
            try:
                if mc.scope != "all" and ctx.visibility != mc.scope:
                    results.append((member.repo, mc.check, f"skipped ({mc.scope}-only)"))
                    continue
                desired = expand_managed_config(manifest_dir, mc)
                outcome = sync_member_config(
                    ctx, mc.check, desired, assume_yes, confirm_fn
                )
            except GhError as e:
                outcome = f"error: {e}"
            results.append((member.repo, mc.check, outcome))
    return results


def fleet_lock_rows(ctx: RepoContext) -> list[dict]:
    """Member-side lock enforcement, run inside every audit.

    A repo that declares `fleet = "owner/repo"` fetches that captain's
    housecaptain.toml; locked keys set locally become required failures, and
    locked check severities come from fleet policy — law, not expectation.
    This is what makes a self-excepting PR (add stray file + allow it in the
    same diff) fail its own CI in the act."""
    from .context import GhError

    fleet = ctx.config.fleet
    if not fleet:
        return []

    def config_row(details: str, note: str = "") -> dict:
        return {
            "check": "config",
            "status": "fail",
            "severity": "required",
            "details": details,
            "note": note,
            "fixable": False,
        }

    try:
        text = _file_text(RepoContext(fleet), "housecaptain.toml")
    except GhError as e:
        return [config_row(f"declared fleet {fleet} is unreachable: {e}")]
    if text is None:
        return [
            config_row(f'fleet = "{fleet}" declared but no housecaptain.toml there')
        ]
    try:
        policy = tomllib.loads(text).get("policy", {})
    except tomllib.TOMLDecodeError:
        return [config_row(f"housecaptain.toml at {fleet} does not parse")]

    locked = list(policy.get("locked", []))
    rows = [
        config_row(
            f"{key} is locked by fleet {fleet} — remove the local override",
            note="fleet law beats local config for locked keys",
        )
        for key in lock_violations(ctx.config.raw, locked)
    ]
    ctx.config.apply_locked(locked, policy.get("checks", {}))
    return rows


def dispatch_self_audit(ctx: RepoContext, workflow_path: str) -> str:
    """Trigger a member's self-audit now — the fleet's 'now' button, so new
    checks don't wait a week of crons to reach everyone."""
    from .context import GhError

    workflows = ctx.api(f"repos/{ctx.repo}/actions/workflows").get("workflows", [])
    match = next((w for w in workflows if w.get("path") == workflow_path), None)
    if match is None:
        return "workflow not found"
    try:
        ctx.api(
            f"repos/{ctx.repo}/actions/workflows/{match['id']}/dispatches",
            method="POST",
            input={"ref": ctx.default_branch},
        )
    except GhError as e:
        if e.status == 422:
            return "not dispatchable — workflow lacks the workflow_dispatch trigger"
        if e.status == 403:
            return "token can't dispatch here (needs actions: write)"
        raise
    return "dispatched"

import base64

import pytest

from housekeeper.captain import (
    ManagedConfig,
    captain_member,
    expand_managed_config,
    load_manifest,
    managed_config_notes,
    policy_conflicts,
)
from housekeeper.context import GhError

MANIFEST = """\
name = "powderworks"

[[member]]
repo = "zmaril/housekeeping"

[[member]]
repo = "zmaril/entl"
note = "pre-release"
parked = true

[policy.checks]
conventional-commits = "required"

[[policy.required-file]]
path = "notes/design.md"
scope = "public"
"""

GOOD_WORKFLOW = """\
name: housekeeping
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 7 * * 1"
  workflow_dispatch:
jobs:
  housekeeping:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: zmaril/housekeeping@v1
"""


def b64(text):
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


class FleetCtx:
    default_branch = "main"

    def __init__(
        self, repo="o/r", files=None, conclusion="success", visibility="public"
    ):
        self.repo = repo
        self._files = files or {}
        self._conclusion = conclusion
        self.visibility = visibility

    def api(self, path, params=None):
        if path.endswith("/actions/workflows"):
            return {
                "workflows": [
                    {"id": 1, "path": p}
                    for p in self._files
                    if p.startswith(".github/workflows/")
                ]
            }
        if "/actions/workflows/1/runs" in path:
            return {
                "workflow_runs": [{"conclusion": self._conclusion, "html_url": "u"}]
            }
        raise AssertionError(path)

    def try_api(self, path, **kwargs):
        if path.endswith("/contents/.github/workflows"):
            return [
                {"name": p.split("/")[-1], "path": p}
                for p in self._files
                if p.startswith(".github/workflows/")
            ]
        for file_path, text in self._files.items():
            if path.endswith(f"/contents/{file_path}"):
                return b64(text)
        return None


def test_manifest_parses(tmp_path):
    path = tmp_path / "housecaptain.toml"
    path.write_text(MANIFEST)
    manifest = load_manifest(path)
    assert manifest.name == "powderworks"
    assert [m.repo for m in manifest.members] == ["zmaril/housekeeping", "zmaril/entl"]
    assert manifest.members[1].note == "pre-release"
    assert manifest.members[1].parked is True
    assert manifest.members[0].parked is False
    assert manifest.policy_checks == {"conventional-commits": "required"}
    assert manifest.required_files[0].path == "notes/design.md"
    assert manifest.required_files[0].scope == "public"


def test_required_file_missing_fails():
    from housekeeper.captain import RequiredFile

    required = [RequiredFile("notes/design.md", "public")]
    ctx = FleetCtx(files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW})
    report = captain_member(ctx, {}, required)
    assert report.status == "fail"
    assert "missing notes/design.md" in report.details

    private = FleetCtx(
        files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW},
        visibility="private",
    )
    assert captain_member(private, {}, required).status == "ok"  # public-scoped

    has_it = FleetCtx(
        files={
            ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
            "notes/design.md": "# design",
        }
    )
    assert captain_member(has_it, {}, required).status == "ok"


CAPTAIN_WORKFLOW = """\
name: housecaptain
on:
  push:
    branches: [main]
  schedule:
    - cron: "0 8 * * 1"
jobs:
  captain:
    steps:
      - uses: zmaril/housekeeping@v1
        with:
          captain: housecaptain.toml
"""


def test_self_auditing_member_is_ok():
    ctx = FleetCtx(files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW})
    report = captain_member(ctx, {})
    assert report.status == "ok", report.details


def test_captain_workflow_is_not_mistaken_for_self_audit():
    # The flagship has both; the captain workflow sorts first alphabetically
    # and also contains housekeeping@ — it must not satisfy the check.
    ctx = FleetCtx(
        files={
            ".github/workflows/housecaptain.yml": CAPTAIN_WORKFLOW,
            ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
        }
    )
    report = captain_member(ctx, {})
    assert report.status == "ok", report.details

    only_captain = FleetCtx(
        files={".github/workflows/housecaptain.yml": CAPTAIN_WORKFLOW}
    )
    assert captain_member(only_captain, {}).status == "fail"


def test_member_without_workflow_fails():
    report = captain_member(FleetCtx(files={}), {})
    assert report.status == "fail"
    assert "isn't auditing itself" in report.details


def test_missing_trigger_and_red_run_fail():
    workflow = GOOD_WORKFLOW.replace('  schedule:\n    - cron: "0 7 * * 1"\n', "")
    ctx = FleetCtx(
        files={".github/workflows/housekeeping.yml": workflow}, conclusion="failure"
    )
    report = captain_member(ctx, {})
    assert report.status == "fail"
    assert "schedule" in report.details and "failure" in report.details


def test_policy_conflict_is_surfaced():
    ctx = FleetCtx(
        files={
            ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
            ".housekeeping.toml": '[checks]\nconventional-commits = "off"\n',
        }
    )
    report = captain_member(ctx, {"conventional-commits": "required"})
    assert report.status == "conflict"
    assert "'off'" in report.details and "'required'" in report.details


def test_unknown_policy_keys_are_surfaced(tmp_path):
    path = tmp_path / "housecaptain.toml"
    path.write_text(MANIFEST + '\n[policy.cheks]\ntypo = "oops"\n')
    manifest = load_manifest(path)
    assert manifest.unknown_policy == ["cheks"]


def test_dispatch_outcomes():
    from housekeeper.captain import dispatch_self_audit
    from housekeeper.context import GhError

    class DispatchCtx(FleetCtx):
        def __init__(self, status=None):
            super().__init__(
                files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW}
            )
            self._status = status
            self.dispatched = False

        def api(self, path, params=None, method="GET", input=None):
            if path.endswith("/dispatches"):
                if self._status:
                    raise GhError(self._status, "nope")
                self.dispatched = True
                return True
            return super().api(path, params)

    happy = DispatchCtx()
    assert (
        dispatch_self_audit(happy, ".github/workflows/housekeeping.yml") == "dispatched"
    )
    assert happy.dispatched
    assert "not dispatchable" in dispatch_self_audit(
        DispatchCtx(status=422), ".github/workflows/housekeeping.yml"
    )
    assert "actions: write" in dispatch_self_audit(
        DispatchCtx(status=403), ".github/workflows/housekeeping.yml"
    )


LOCKED_MANIFEST = (
    MANIFEST.replace(
        'name = "powderworks"',
        'name = "powderworks"\ncaptain = "zmaril/powderworks"',
    )
    + '\n[policy]\nlocked = ["checks.stray-files", "stray-files.allow"]\n'
)


def test_locked_manifest_parses_and_requires_captain(tmp_path):
    import pytest as _pytest

    path = tmp_path / "housecaptain.toml"
    path.write_text(LOCKED_MANIFEST)
    manifest = load_manifest(path)
    assert manifest.locked == ["checks.stray-files", "stray-files.allow"]
    assert manifest.captain == "zmaril/powderworks"

    path.write_text(MANIFEST + '\n[policy]\nlocked = ["checks.stray-files"]\n')
    with _pytest.raises(ValueError, match="captain"):
        load_manifest(path)


def test_lock_violations_pure():
    from housekeeper.captain import lock_violations

    config = {"checks": {"stray-files": "off"}, "stray-files": {"allow": ["x.md"]}}
    locked = ["checks.stray-files", "stray-files.allow", "checks.website"]
    assert lock_violations(config, locked) == [
        "checks.stray-files",
        "stray-files.allow",
    ]
    assert lock_violations({}, locked) == []


def test_captain_flags_locked_overrides_and_missing_fleet_declaration():
    locked = ["stray-files.allow"]
    sneaky = FleetCtx(
        files={
            ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
            ".housekeeping.toml": 'fleet = "zmaril/powderworks"\n'
            '[stray-files]\nallow = ["scratch.md"]\n',
        }
    )
    report = captain_member(sneaky, {}, None, locked, "zmaril/powderworks")
    assert report.status == "conflict"
    assert "locked by fleet policy" in report.details

    undeclared = FleetCtx(files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW})
    report = captain_member(undeclared, {}, None, locked, "zmaril/powderworks")
    assert report.status == "conflict"
    assert "declare fleet" in report.details

    lawful = FleetCtx(
        files={
            ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
            ".housekeeping.toml": 'fleet = "zmaril/powderworks"\n',
        }
    )
    assert captain_member(lawful, {}, None, locked, "zmaril/powderworks").status == "ok"


def test_apply_locked_is_law():
    from housekeeper.config import Config

    config = Config(
        {"checks": {"stray-files": "off"}, "stray-files": {"allow": ["scratch.md"]}}
    )
    config.apply_locked(
        ["checks.stray-files", "stray-files.allow"], {"stray-files": "required"}
    )
    assert config.severity("stray-files", "public") == "required"
    assert config.section("stray-files").get("allow") is None


STYLELINT_MC = """
[[policy.managed-config]]
check = "stylelint"
paths = { ".stylelintrc.json" = ".fleet/stylelintrc.json" }
"""


def test_managed_config_parses(tmp_path):
    path = tmp_path / "housecaptain.toml"
    path.write_text(MANIFEST + STYLELINT_MC)
    manifest = load_manifest(path)
    mc = manifest.managed_configs[0]
    assert mc.check == "stylelint"
    assert mc.paths == {".stylelintrc.json": ".fleet/stylelintrc.json"}
    assert mc.scope == "all"


def test_managed_config_source_must_live_under_fleet(tmp_path):
    path = tmp_path / "housecaptain.toml"
    path.write_text(
        MANIFEST + '\n[[policy.managed-config]]\ncheck = "vale"\n'
        'paths = { ".vale.ini" = "configs/vale.ini" }\n'
    )
    with pytest.raises(ValueError, match=r"\.fleet"):
        load_manifest(path)


def test_managed_config_rejects_bad_scope(tmp_path):
    path = tmp_path / "housecaptain.toml"
    path.write_text(
        MANIFEST + '\n[[policy.managed-config]]\ncheck = "vale"\nscope = "sometimes"\n'
        'paths = { ".vale.ini" = ".fleet/vale.ini" }\n'
    )
    with pytest.raises(ValueError, match="scope"):
        load_manifest(path)


def test_expand_managed_config_directory(tmp_path):
    vocab = tmp_path / ".fleet" / "vale" / "styles" / "Vocab"
    vocab.mkdir(parents=True)
    (vocab / "accept.txt").write_text("Housekeeper\n")
    mc = ManagedConfig("vale", {"styles/": ".fleet/vale/styles/"})
    assert expand_managed_config(tmp_path, mc) == {
        "styles/Vocab/accept.txt": "Housekeeper\n"
    }


def test_managed_config_notes_flag_drift(tmp_path):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "stylelintrc.json").write_text('{"extends": "fleet"}\n')
    mc = ManagedConfig("stylelint", {".stylelintrc.json": ".fleet/stylelintrc.json"})

    stale = FleetCtx(files={".stylelintrc.json": "{}\n"})
    notes = managed_config_notes(stale, [mc], tmp_path)
    assert notes and "stylelint config drifts" in notes[0] and "stale" in notes[0]

    synced = FleetCtx(files={".stylelintrc.json": '{"extends": "fleet"}\n'})
    assert managed_config_notes(synced, [mc], tmp_path) == []


def test_managed_config_drift_surfaces_on_captain_report(tmp_path):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "stylelintrc.json").write_text('{"extends": "fleet"}\n')
    mc = ManagedConfig("stylelint", {".stylelintrc.json": ".fleet/stylelintrc.json"})
    ctx = FleetCtx(
        files={
            ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
            ".stylelintrc.json": "{}\n",
        }
    )
    report = captain_member(ctx, {}, managed_configs=[mc], manifest_dir=tmp_path)
    # Drift is informational — the member is still "ok", just noted.
    assert report.status == "ok"
    assert "stylelint config drifts" in report.note


def _tree_sha(base_tree, entries):
    key = sorted((e["path"], e["content"]) for e in entries)
    return f"tree:{base_tree}:{key!r}"


class SyncCtx:
    """Fake git-data API for exercising sync_member_config without a network."""

    default_branch = "main"

    def __init__(self, contents=None, branch_tree=None, open_pr=False, repo="o/r"):
        self.repo = repo
        self._contents = contents or {}  # member path -> content at default branch
        self._branch_tree = branch_tree  # tree sha of the sync branch tip, or None
        self._open_pr = open_pr
        self.writes = []  # (method, path) for every mutating call

    def try_api(self, path, none_on=(404,), **kwargs):
        try:
            return self.api(path, **kwargs)
        except GhError as e:
            if e.status in none_on:
                return None
            raise

    def api(self, path, method="GET", input=None, params=None):
        # Creating a tree is a content-addressed computation (a dangling object),
        # not a mutation — only commits/refs/pulls count as churn.
        if method != "GET" and not path.endswith("/git/trees"):
            self.writes.append((method, path))
        if "/contents/" in path:
            key = path.split("/contents/", 1)[1]
            if key in self._contents:
                return b64(self._contents[key])
            raise GhError(404, "not found")
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "HEAD"}}
        if "/git/ref/heads/housekeeping/fleet-config-" in path:
            if self._branch_tree is None:
                raise GhError(404, "no such branch")
            return {"object": {"sha": "BRANCHHEAD"}}
        if path.endswith("/git/commits/HEAD"):
            return {"tree": {"sha": "T_main"}}
        if path.endswith("/git/commits/BRANCHHEAD"):
            return {"tree": {"sha": self._branch_tree}}
        if path.endswith("/git/trees"):
            return {"sha": _tree_sha(input["base_tree"], input["tree"])}
        if path.endswith("/git/commits"):
            return {"sha": "NEWCOMMIT"}
        if path.endswith("/git/refs"):
            return {"ref": input["ref"]}
        if "/git/refs/heads/" in path:
            return True
        if "/pulls?" in path:
            return [{"number": 1}] if self._open_pr else []
        if path.endswith("/pulls"):
            return {"number": 2, "html_url": "u"}
        raise AssertionError(path)


def _stylelint_mc(tmp_path, canonical='{"extends": "fleet"}\n'):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "stylelintrc.json").write_text(canonical)
    mc = ManagedConfig("stylelint", {".stylelintrc.json": ".fleet/stylelintrc.json"})
    return mc, expand_managed_config(tmp_path, mc)


def test_sync_opens_pr_on_drift(tmp_path):
    from housekeeper.captain import sync_member_config

    _, desired = _stylelint_mc(tmp_path)
    ctx = SyncCtx(contents={".stylelintrc.json": "{}\n"})
    outcome = sync_member_config(ctx, "stylelint", desired, assume_yes=True)
    assert outcome == "sync PR opened"
    methods = {m for m, _ in ctx.writes}
    assert methods == {"POST"}
    assert any(p.endswith("/pulls") for _, p in ctx.writes)


def test_sync_noop_when_in_sync(tmp_path):
    from housekeeper.captain import sync_member_config

    _, desired = _stylelint_mc(tmp_path)
    ctx = SyncCtx(contents={".stylelintrc.json": '{"extends": "fleet"}\n'})
    assert sync_member_config(ctx, "stylelint", desired, assume_yes=True) == "in sync"
    assert ctx.writes == []


def test_sync_skips_when_branch_already_current(tmp_path):
    from housekeeper.captain import sync_member_config

    _, desired = _stylelint_mc(tmp_path)
    entries = [
        {"path": p, "mode": "100644", "type": "blob", "content": c}
        for p, c in sorted(desired.items())
    ]
    ctx = SyncCtx(
        contents={".stylelintrc.json": "{}\n"},
        branch_tree=_tree_sha("T_main", entries),
        open_pr=True,
    )
    outcome = sync_member_config(ctx, "stylelint", desired, assume_yes=True)
    assert outcome == "sync PR already up to date"
    assert ctx.writes == []  # no new commit/ref churn


def test_sync_updates_open_pr_when_content_moves(tmp_path):
    from housekeeper.captain import sync_member_config

    _, desired = _stylelint_mc(tmp_path)
    ctx = SyncCtx(
        contents={".stylelintrc.json": "{}\n"},
        branch_tree="tree:stale",  # an existing PR built from older canonical
        open_pr=True,
    )
    outcome = sync_member_config(ctx, "stylelint", desired, assume_yes=True)
    assert outcome == "sync PR updated"
    assert ("PATCH", "repos/o/r/git/refs/heads/housekeeping/fleet-config-stylelint") in [
        (m, p) for m, p in ctx.writes
    ]


def test_sync_respects_confirmation(tmp_path):
    from housekeeper.captain import sync_member_config

    _, desired = _stylelint_mc(tmp_path)
    ctx = SyncCtx(contents={".stylelintrc.json": "{}\n"})
    outcome = sync_member_config(
        ctx, "stylelint", desired, assume_yes=False, confirm_fn=lambda _: False
    )
    assert outcome == "skipped"
    assert ctx.writes == []


def test_policy_silence_and_agreement_are_fine():
    silent = FleetCtx(files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW})
    assert policy_conflicts(silent, {"conventional-commits": "required"}) == []
    agreeing = FleetCtx(
        files={".housekeeping.toml": '[checks]\nconventional-commits = "required"\n'}
    )
    assert policy_conflicts(agreeing, {"conventional-commits": "required"}) == []

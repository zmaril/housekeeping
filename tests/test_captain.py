import base64

from housekeeper.captain import (
    captain_member,
    load_manifest,
    policy_conflicts,
)

MANIFEST = """\
name = "powderworks"

[[member]]
repo = "zmaril/housekeeping"

[[member]]
repo = "zmaril/entl"
note = "pre-release"

[policy.checks]
conventional-commits = "required"
"""

GOOD_WORKFLOW = """\
name: housekeeping
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 7 * * 1"
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

    def __init__(self, repo="o/r", files=None, conclusion="success"):
        self.repo = repo
        self._files = files or {}
        self._conclusion = conclusion

    def api(self, path, params=None):
        if path.endswith("/actions/workflows"):
            return {"workflows": [
                {"id": 1, "path": p} for p in self._files if p.startswith(".github/workflows/")
            ]}
        if "/actions/workflows/1/runs" in path:
            return {"workflow_runs": [{"conclusion": self._conclusion, "html_url": "u"}]}
        raise AssertionError(path)

    def try_api(self, path, **kwargs):
        if path.endswith("/contents/.github/workflows"):
            return [{"name": p.split("/")[-1], "path": p} for p in self._files
                    if p.startswith(".github/workflows/")]
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
    assert manifest.policy_checks == {"conventional-commits": "required"}


def test_self_auditing_member_is_ok():
    ctx = FleetCtx(files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW})
    report = captain_member(ctx, {})
    assert report.status == "ok", report.details


def test_member_without_workflow_fails():
    report = captain_member(FleetCtx(files={}), {})
    assert report.status == "fail"
    assert "isn't auditing itself" in report.details


def test_missing_trigger_and_red_run_fail():
    workflow = GOOD_WORKFLOW.replace("  schedule:\n    - cron: \"0 7 * * 1\"\n", "")
    ctx = FleetCtx(files={".github/workflows/housekeeping.yml": workflow},
                   conclusion="failure")
    report = captain_member(ctx, {})
    assert report.status == "fail"
    assert "schedule" in report.details and "failure" in report.details


def test_policy_conflict_is_surfaced():
    ctx = FleetCtx(files={
        ".github/workflows/housekeeping.yml": GOOD_WORKFLOW,
        ".housekeeping.toml": '[checks]\nconventional-commits = "off"\n',
    })
    report = captain_member(ctx, {"conventional-commits": "required"})
    assert report.status == "conflict"
    assert "'off'" in report.details and "'required'" in report.details


def test_policy_silence_and_agreement_are_fine():
    silent = FleetCtx(files={".github/workflows/housekeeping.yml": GOOD_WORKFLOW})
    assert policy_conflicts(silent, {"conventional-commits": "required"}) == []
    agreeing = FleetCtx(files={
        ".housekeeping.toml": '[checks]\nconventional-commits = "required"\n'})
    assert policy_conflicts(agreeing, {"conventional-commits": "required"}) == []

from housekeeper.checks.ci import ci_green
from housekeeper.registry import Status


class FakeCtx:
    repo = "o/r"
    default_branch = "main"

    def __init__(self, workflows, latest_run_by_id):
        self._workflows = workflows
        self._latest = latest_run_by_id

    def api(self, path, params=None):
        if path.endswith("/actions/workflows"):
            return {"workflows": self._workflows}
        workflow_id = int(path.split("/workflows/")[1].split("/")[0])
        latest = self._latest.get(workflow_id)
        return {"workflow_runs": [latest] if latest else []}


def wf(id, name, path=".github/workflows/x.yml", state="active"):
    return {"id": id, "name": name, "path": path, "state": state}


def run(conclusion):
    return {"conclusion": conclusion, "html_url": "https://example.test/run"}


def test_dynamic_workflows_are_ignored():
    ctx = FakeCtx(
        [wf(1, "ci"), wf(2, "Dependency Graph", path="dynamic/graph"),
         wf(3, "Dependabot Updates", path="dynamic/dependabot")],
        {1: run("success"), 2: run("failure"), 3: run("failure")},
    )
    result = ci_green(ctx)
    assert result.status == Status.PASS
    assert "ci" in result.details


def test_every_workflow_must_be_green():
    ctx = FakeCtx(
        [wf(1, "ci"), wf(2, "straitjacket")],
        {1: run("success"), 2: run("failure")},
    )
    result = ci_green(ctx)
    assert result.status == Status.FAIL
    assert "straitjacket" in result.details
    assert "ci" not in result.details.split("red on main:")[1].split("straitjacket")[0]


def test_workflow_without_main_runs_is_noted_not_failed():
    ctx = FakeCtx([wf(1, "ci"), wf(2, "release")], {1: run("success")})
    result = ci_green(ctx)
    assert result.status == Status.PASS
    assert "release" in result.note


def test_no_completed_runs_at_all_skips():
    ctx = FakeCtx([wf(1, "ci")], {})
    assert ci_green(ctx).status == Status.SKIP


def test_disabled_workflows_do_not_gate():
    ctx = FakeCtx(
        [wf(1, "ci"), wf(2, "old", state="disabled_manually")],
        {1: run("success"), 2: run("failure")},
    )
    assert ci_green(ctx).status == Status.PASS


def test_no_real_workflows_skips():
    ctx = FakeCtx([wf(1, "Dependency Graph", path="dynamic/graph")], {1: run("success")})
    assert ci_green(ctx).status == Status.SKIP

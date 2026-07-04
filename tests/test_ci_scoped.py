from housekeeper.checks.ci_scoped import ci_scoped
from housekeeper.registry import Status


def write_wf(tmp_path, name, content):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


class Ctx:
    def __init__(self, tmp_path):
        self.workdir = tmp_path


def test_flags_heavy_unscoped_job(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        """\
name: CI
on: {pull_request: {}}
jobs:
  desktop:
    name: Desktop compile
    steps:
      - {run: "sudo apt-get install -y libwebkit2gtk-4.1-dev"}
      - {run: "cargo check --manifest-path src-tauri/Cargo.toml"}
""",
    )
    r = ci_scoped(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "Desktop compile" in r.details


def test_scoped_by_job_if_and_needs(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        """\
name: CI
on: {pull_request: {}}
jobs:
  changes:
    outputs: {tauri: x}
    steps: [{run: filter}]
  desktop:
    needs: changes
    if: ${{ needs.changes.outputs.tauri == 'true' }}
    steps: [{run: "cargo check"}]
""",
    )
    assert ci_scoped(Ctx(tmp_path)).status == Status.PASS


def test_scoped_by_workflow_paths_filter(tmp_path):
    write_wf(
        tmp_path,
        "desktop.yml",
        "name: D\non: {pull_request: {paths: ['src-tauri/**']}}\n"
        "jobs: {x: {steps: [{run: cargo build}]}}\n",
    )
    assert ci_scoped(Ctx(tmp_path)).status == Status.PASS


def test_light_jobs_are_not_flagged(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {pull_request: {}}\n"
        "jobs: {test: {steps: [{run: bun install}, {run: bun test}]}}\n",
    )
    assert ci_scoped(Ctx(tmp_path)).status == Status.PASS


def test_push_only_workflow_ignored(tmp_path):
    write_wf(
        tmp_path,
        "nightly.yml",
        "name: N\non: {schedule: [{cron: '0 3 * * *'}]}\n"
        "jobs: {desktop: {steps: [{run: cargo build}]}}\n",
    )
    assert ci_scoped(Ctx(tmp_path)).status == Status.PASS

from housekeeper.checks.required_checks import (
    pr_check_jobs,
    required_checks,
    required_contexts,
)
from housekeeper.registry import Status


def write_wf(tmp_path, name, content):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


CI = """\
name: CI
on: {pull_request: {}}
jobs:
  changes:
    outputs: {code: x}
    steps: [{run: filter}]
  test:
    name: Tests (bun test)
    steps: [{run: bun test}]
  build:
    steps: [{run: bun run build}]
"""


def test_pr_check_jobs_uses_names_and_skips_fanout_helpers(tmp_path):
    write_wf(tmp_path, "ci.yml", CI)
    # `changes` carries outputs → excluded; `test` uses its name; `build` falls back to id.
    assert pr_check_jobs(tmp_path) == {"Tests (bun test)", "build"}


def test_pr_check_jobs_ignores_non_pr_workflows(tmp_path):
    write_wf(
        tmp_path,
        "release.yml",
        "name: R\non: {push: {tags: ['v*']}}\njobs: {x: {steps: [{run: go build}]}}\n",
    )
    assert pr_check_jobs(tmp_path) == set()


def test_required_contexts_from_ruleset_and_classic():
    class Ctx:
        repo, default_branch = "o/r", "main"

        def try_api(self, path, none_on=(404,), **kw):
            if "/rules/branches/" in path:
                return [
                    {"type": "pull_request"},
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "test"},
                                {"context": "lint"},
                            ]
                        },
                    },
                ]
            if path.endswith("/contexts"):
                return ["build"]
            return None

    configured, contexts = required_contexts(Ctx())
    assert configured is True
    assert contexts == {"test", "lint", "build"}


class FakeCtx:
    repo, default_branch = "o/r", "main"

    def __init__(self, tmp_path, rules, classic=None, visibility="public"):
        self.workdir = tmp_path
        self.visibility = visibility
        self._rules = rules
        self._classic = classic

    def try_api(self, path, none_on=(404,), **kw):
        if "/rules/branches/" in path:
            return self._rules
        if path.endswith("/contexts"):
            return self._classic
        return None


def test_fails_when_branch_requires_no_checks(tmp_path):
    write_wf(tmp_path, "ci.yml", CI)
    r = required_checks(FakeCtx(tmp_path, rules=[{"type": "pull_request"}]))
    assert r.status == Status.FAIL
    assert "requires no status checks" in r.details


def test_fails_when_a_pr_check_isnt_required(tmp_path):
    write_wf(tmp_path, "ci.yml", CI)
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "Tests (bun test)"}]},
        }
    ]
    r = required_checks(FakeCtx(tmp_path, rules=rules))
    assert r.status == Status.FAIL
    assert "build" in r.details  # the one not required


def test_passes_when_all_pr_checks_required(tmp_path):
    write_wf(tmp_path, "ci.yml", CI)
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [
                    {"context": "Tests (bun test)"},
                    {"context": "build"},
                ]
            },
        }
    ]
    r = required_checks(FakeCtx(tmp_path, rules=rules))
    assert r.status == Status.PASS


def test_private_repo_without_readable_protection_skips(tmp_path):
    write_wf(tmp_path, "ci.yml", CI)
    r = required_checks(FakeCtx(tmp_path, rules=None, visibility="private"))
    assert r.status == Status.SKIP


def test_no_pr_checks_skips(tmp_path):
    write_wf(
        tmp_path,
        "x.yml",
        "name: X\non: {push: {}}\njobs: {a: {steps: [{run: echo}]}}\n",
    )
    r = required_checks(FakeCtx(tmp_path, rules=[]))
    assert r.status == Status.SKIP

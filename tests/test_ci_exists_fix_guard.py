"""`housekeeper fix ci-exists` must never overwrite an existing CI workflow.

ci-exists fails two different ways — no CI at all, or CI that exists but is
missing a test/lint/fmt step for some language. The scaffold only answers the
first. In v0.20.0 it answered both by unconditionally writing
`.github/workflows/ci.yml`, so on a repo whose CI merely lacked a rust fmt step
the fix replaced that repo's entire hand-written workflow with a generic stub.
"""

from types import SimpleNamespace

from housekeeper.checks import ci as ci_module
from housekeeper.config import Config

EXISTING = """\
name: CI
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: bun install --frozen-lockfile
      - run: bun run check
      - run: bun test
"""


def run_fix(tmp_path, monkeypatch, workflow: str | None) -> list:
    """Run the ci-exists fix on a cargo repo, optionally seeded with an existing
    ci.yml, and return the recorded apply_file_fix calls (empty = wrote nothing).

    The rust ecosystem has no rust steps in either case, so ci-exists fails both
    times — only the presence of existing CI should change what the fix does.
    """
    if workflow is not None:
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True, exist_ok=True)
        (workflows / "ci.yml").write_text(workflow)
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n")

    from housekeeper.languages import ECOSYSTEMS

    called: list = []
    monkeypatch.setattr(ci_module, "apply_file_fix", lambda *a, **k: called.append(a))
    ci_module.fix(
        SimpleNamespace(
            workdir=tmp_path, ecosystems=[ECOSYSTEMS["cargo"]], config=Config()
        )
    )
    return called


def test_fix_does_not_clobber_an_existing_workflow(tmp_path, monkeypatch):
    called = run_fix(tmp_path, monkeypatch, EXISTING)

    assert called == [], "fix must not run a file write when workflows already exist"
    assert (tmp_path / ".github" / "workflows" / "ci.yml").read_text() == EXISTING, (
        "existing workflow was modified"
    )


def test_fix_still_scaffolds_when_there_is_no_ci(tmp_path, monkeypatch):
    called = run_fix(tmp_path, monkeypatch, None)

    assert len(called) == 1, "a repo with no CI at all should still get a scaffold"

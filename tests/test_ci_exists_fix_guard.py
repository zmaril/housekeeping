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


def ctx_for(tmp_path, ecosystems):
    return SimpleNamespace(workdir=tmp_path, ecosystems=ecosystems, config=Config())


def write_workflow(tmp_path, name, body):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(body)
    return workflows / name


def test_fix_does_not_clobber_an_existing_workflow(tmp_path, monkeypatch):
    from housekeeper.languages import ECOSYSTEMS

    path = write_workflow(tmp_path, "ci.yml", EXISTING)
    # A rust ecosystem with no rust steps in CI: ci-exists fails, but the repo
    # plainly has CI already, so scaffolding is the wrong answer.
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n")

    called = []
    monkeypatch.setattr(
        ci_module, "apply_file_fix", lambda *a, **k: called.append(a)
    )

    ci_module.fix(ctx_for(tmp_path, [ECOSYSTEMS["cargo"]]))

    assert called == [], "fix must not run a file write when workflows already exist"
    assert path.read_text() == EXISTING, "existing workflow was modified"


def test_fix_still_scaffolds_when_there_is_no_ci(tmp_path, monkeypatch):
    from housekeeper.languages import ECOSYSTEMS

    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n")

    called = []
    monkeypatch.setattr(
        ci_module, "apply_file_fix", lambda *a, **k: called.append(a)
    )

    ci_module.fix(ctx_for(tmp_path, [ECOSYSTEMS["cargo"]]))

    assert len(called) == 1, "a repo with no CI at all should still get a scaffold"

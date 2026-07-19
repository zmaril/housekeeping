"""ci-exists resolves package.json scripts referenced by `bun run <name>` —
found via powdermonkey, whose `bun run check` hides biome from the patterns."""

import json
from types import SimpleNamespace

from housekeeper.checks.ci import ci_exists
from housekeeper.config import Config
from housekeeper.registry import Status

WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bun install --frozen-lockfile
      - run: bun run check
      - run: bun test
"""


def repo_with_check_script(tmp_path, scripts):
    from housekeeper.languages import ECOSYSTEMS

    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(WORKFLOW)
    (tmp_path / "package.json").write_text(json.dumps({"scripts": scripts}))
    return SimpleNamespace(
        workdir=tmp_path,
        ecosystems=[ECOSYSTEMS["bun"]],
        config=Config(),
    )


def test_lint_hidden_in_package_script_is_found(tmp_path):
    ctx = repo_with_check_script(tmp_path, {"check": "biome check src"})
    result = ci_exists(ctx)
    assert result.status == Status.PASS, result.details


def test_script_without_lint_still_fails(tmp_path):
    ctx = repo_with_check_script(tmp_path, {"check": "tsc --noEmit"})
    result = ci_exists(ctx)
    assert result.status == Status.FAIL
    assert "no lint step" in result.details


def test_unparseable_package_json_is_tolerated(tmp_path):
    ctx = repo_with_check_script(tmp_path, {})
    (tmp_path / "package.json").write_text("{not json")
    assert ci_exists(ctx).status == Status.FAIL  # falls back to workflow text only

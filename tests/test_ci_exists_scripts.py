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


# --- nested package.json script resolution ------------------------------------
#
# The js of a Rust-workspace repo often lives in a nested package (e.g. a napi
# binding crate) with no root package.json, and CI runs `bun run check` under
# `working-directory: crates/x-node`, where that crate's package.json maps
# `"check": "biome check ."`. The linter genuinely runs, so resolve_package_scripts
# must resolve run-scripts against EVERY package.json in the tree, not just root.

# `bun run check` under a nested working-directory; the only js lint/fmt signal is
# behind that script. (run_commands only reads step run/uses/name — the
# working-directory is realism, not what the resolver keys off.)
NESTED_WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  node:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: crates/x-node
    steps:
      - uses: actions/checkout@v4
      - run: bun install --frozen-lockfile
      - run: bun run check
      - run: bun test
"""


def nested_repo(tmp_path, workflow_text, nested_dir, scripts, root_scripts=None):
    from dataclasses import replace

    from housekeeper.languages import ECOSYSTEMS

    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(workflow_text)
    pkg = tmp_path / nested_dir
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({"scripts": scripts}))
    if root_scripts is not None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": root_scripts}))
    nested_bun = replace(ECOSYSTEMS["bun"], dir=nested_dir)
    return SimpleNamespace(
        workdir=tmp_path,
        ecosystems=[nested_bun],
        config=Config(),
    )


def test_lint_in_nested_package_script_is_found(tmp_path):
    # The motivating real consumer: zmaril/disponent's crates/disponent-node, whose
    # `bun run check` -> `biome check .` lives in a nested package with no root
    # package.json. Was a false FAIL (js: no lint/fmt step); now credited.
    ctx = nested_repo(
        tmp_path, NESTED_WORKFLOW, "crates/x-node", {"check": "biome check ."}
    )
    result = ci_exists(ctx)
    assert result.status == Status.PASS, result.details


def test_nested_non_linter_script_does_not_satisfy_lint(tmp_path):
    # A resolved script that is NOT a linter/formatter must not spuriously satisfy
    # lint/fmt — resolution widens WHERE we look, it doesn't loosen the patterns.
    build_wf = NESTED_WORKFLOW.replace("bun run check", "bun run build")
    ctx = nested_repo(tmp_path, build_wf, "crates/x-node", {"build": "vite build"})
    result = ci_exists(ctx)
    assert result.status == Status.FAIL
    assert "js: no lint step" in result.details
    assert "js: no fmt step" in result.details


def test_root_and_nested_scripts_are_unioned(tmp_path):
    # A bare root package.json (no linter script) must not shadow the nested one
    # that carries the real linter — script bodies from every package.json union.
    ctx = nested_repo(
        tmp_path,
        NESTED_WORKFLOW,
        "crates/x-node",
        {"check": "biome check ."},
        root_scripts={"dev": "vite"},
    )
    result = ci_exists(ctx)
    assert result.status == Status.PASS, result.details

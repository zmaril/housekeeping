"""Per-language CI coverage, codegen drift wiring, and build targets in CI."""

import json
from types import SimpleNamespace

from housekeeper.checks.builds import builds
from housekeeper.checks.ci import ci_exists
from housekeeper.checks.codegen import codegen_drift
from housekeeper.config import Config
from housekeeper.context import detect_ecosystems
from housekeeper.languages import ECOSYSTEMS
from housekeeper.registry import Status

RUST = ECOSYSTEMS["cargo"]
RUBY = ECOSYSTEMS["ruby"]
BUN = ECOSYSTEMS["bun"]


def repo(tmp_path, workflow_text, ecosystems=(), config=None, scripts=None):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(workflow_text)
    if scripts is not None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": scripts}))
    return SimpleNamespace(
        workdir=tmp_path, ecosystems=list(ecosystems), config=Config(config)
    )


RUST_ONLY_CI = """\
on:
  push:
  pull_request:
jobs:
  rust:
    steps:
      - run: cargo fmt --check
      - run: cargo clippy -- -D warnings
      - run: cargo test
"""


def test_ruby_detected(tmp_path):
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'")
    names = [e.name for e in detect_ecosystems(tmp_path)]
    assert "ruby" in names


def test_each_language_needs_its_own_jobs(tmp_path):
    ctx = repo(tmp_path, RUST_ONLY_CI, ecosystems=[RUST, RUBY])
    result = ci_exists(ctx)
    assert result.status == Status.FAIL
    for gap in ("ruby: no test step", "ruby: no lint step", "ruby: no fmt step"):
        assert gap in result.details
    assert "rust" not in result.details


def test_all_languages_covered_passes(tmp_path):
    ci = (
        RUST_ONLY_CI
        + "      - run: bundle exec rubocop\n      - run: bundle exec rspec\n"
    )
    ctx = repo(tmp_path, ci, ecosystems=[RUST, RUBY])
    result = ci_exists(ctx)
    assert result.status == Status.PASS, result.details
    assert "ruby" in result.details and "rust" in result.details


def test_codegen_undeclared_skips(tmp_path):
    ctx = repo(tmp_path, RUST_ONLY_CI)
    assert codegen_drift(ctx).status == Status.SKIP


def test_codegen_wiring_and_diff_guard(tmp_path):
    config = {"codegen": [{"name": "bindings", "command": "make bindgen"}]}
    missing = repo(tmp_path, RUST_ONLY_CI, config=config)
    result = codegen_drift(missing)
    assert result.status == Status.FAIL
    assert "CI never runs 'make bindgen'" in result.details

    no_guard = repo(
        tmp_path, RUST_ONLY_CI + "      - run: make bindgen\n", config=config
    )
    result = codegen_drift(no_guard)
    assert result.status == Status.FAIL
    assert "zero drift" in result.details or "git diff --exit-code" in result.details

    wired = repo(
        tmp_path,
        RUST_ONLY_CI + "      - run: make bindgen\n      - run: git diff --exit-code\n",
        config=config,
    )
    assert codegen_drift(wired).status == Status.PASS


def test_builds_skips_without_targets(tmp_path):
    ctx = repo(tmp_path, RUST_ONLY_CI, scripts={"dev": "bun run watch"})
    assert builds(ctx).status == Status.SKIP


def test_uncovered_build_script_fails(tmp_path):
    ctx = repo(
        tmp_path,
        RUST_ONLY_CI + "      - run: bun test\n",
        ecosystems=[BUN],
        scripts={"build:web": "bun build src/main.tsx"},
    )
    result = builds(ctx)
    assert result.status == Status.FAIL
    assert "build:web" in result.details


def test_transitive_build_coverage_passes(tmp_path):
    # CI runs build:compile whose body invokes build:web — both count.
    ctx = repo(
        tmp_path,
        RUST_ONLY_CI + "      - run: bun run build:compile\n",
        ecosystems=[BUN],
        scripts={
            "build:web": "bun build src/main.tsx",
            "build:compile": "bun run build:web && bun build --compile bin/x.ts",
        },
    )
    result = builds(ctx)
    assert result.status == Status.PASS, result.details


def test_tauri_needs_nightly_full_and_pr_compile(tmp_path):
    (tmp_path / "src-tauri").mkdir()
    bare = repo(tmp_path, RUST_ONLY_CI, scripts={})
    result = builds(bare)
    assert result.status == Status.FAIL
    assert "scheduled workflow" in result.details and "compile check" in result.details

    workflows = tmp_path / ".github" / "workflows"
    (workflows / "ci.yml").write_text(
        RUST_ONLY_CI + "      - run: cargo check --manifest-path src-tauri/Cargo.toml\n"
    )
    (workflows / "nightly.yml").write_text(
        "on:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  desktop:\n    steps:\n"
        "      - run: bun run tauri build\n"
    )
    covered = SimpleNamespace(workdir=tmp_path, ecosystems=[], config=Config(None))
    assert builds(covered).status == Status.PASS

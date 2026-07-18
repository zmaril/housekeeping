"""coverage check: presence-only, per detected language ecosystem.

Fixtures are temp repos with and without a coverage tool wired up; the check must
PASS when every detected ecosystem has one, FAIL (advisory) when one is missing,
and SKIP when no rust/js/python ecosystem is present.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from housekeeper.checks.coverage import coverage
from housekeeper.languages import ECOSYSTEMS
from housekeeper.registry import Status


def ctx(tmp_path: Path, *ecosystems: str) -> SimpleNamespace:
    return SimpleNamespace(
        workdir=tmp_path,
        ecosystems=[ECOSYSTEMS[name] for name in ecosystems],
    )


def write_wf(tmp_path: Path, name: str, content: str) -> None:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


# ---- Rust ----


def test_rust_without_coverage_fails(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    write_wf(
        tmp_path, "ci.yml", "jobs:\n  test:\n    steps:\n      - run: cargo test\n"
    )
    result = coverage(ctx(tmp_path, "cargo"))
    assert result.status == Status.FAIL
    assert "rust" in result.details and "llvm-cov" in result.details


def test_rust_with_llvm_cov_in_ci_passes(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    write_wf(
        tmp_path,
        "cov.yml",
        "jobs:\n  cov:\n    steps:\n      - run: cargo llvm-cov --summary-only\n",
    )
    result = coverage(ctx(tmp_path, "cargo"))
    assert result.status == Status.PASS
    assert "llvm-cov" in result.details


def test_rust_with_tarpaulin_in_justfile_passes(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "justfile").write_text("cov:\n    cargo tarpaulin --out Xml\n")
    assert coverage(ctx(tmp_path, "cargo")).status == Status.PASS


# ---- Python ----


def test_python_without_coverage_fails(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    result = coverage(ctx(tmp_path, "uv"))
    assert result.status == Status.FAIL
    assert "python" in result.details and "pytest-cov" in result.details


def test_python_pytest_cov_in_pyproject_passes(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\ndev = ['pytest-cov>=5']\n"
    )
    assert coverage(ctx(tmp_path, "uv")).status == Status.PASS


def test_python_tool_coverage_table_passes(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.coverage.run]\nsource = ['pkg']\n")
    assert coverage(ctx(tmp_path, "uv")).status == Status.PASS


# ---- JS ----


def test_js_with_coverage_script_passes(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "vitest run --coverage"}}'
    )
    assert coverage(ctx(tmp_path, "bun")).status == Status.PASS


def test_js_bunfig_coverage_passes(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "bunfig.toml").write_text("[test]\ncoverage = true\n")
    assert coverage(ctx(tmp_path, "bun")).status == Status.PASS


def test_js_without_coverage_fails(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "bun test"}}')
    result = coverage(ctx(tmp_path, "bun"))
    assert result.status == Status.FAIL
    assert "js" in result.details


# ---- Generic + multi-ecosystem + skip ----


def test_generic_codecov_config_covers_ecosystem(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "codecov.yml").write_text("coverage:\n  status:\n")
    result = coverage(ctx(tmp_path, "cargo"))
    assert result.status == Status.PASS
    assert "codecov.yml" in result.details


def test_mixed_one_covered_one_missing_fails(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    write_wf(
        tmp_path, "cov.yml", "jobs:\n  c:\n    steps:\n      - run: cargo llvm-cov\n"
    )
    result = coverage(ctx(tmp_path, "cargo", "uv"))
    assert result.status == Status.FAIL
    # rust is satisfied, python is the gap — the message names the missing one.
    assert "python" in result.details
    assert "rust" in result.note  # the satisfied one is reported in the note


def test_no_recognized_ecosystem_skips(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert coverage(ctx(tmp_path, "go")).status == Status.SKIP

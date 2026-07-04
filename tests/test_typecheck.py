import json
from types import SimpleNamespace

from housekeeper.checks.typecheck import typecheck
from housekeeper.registry import Status

WORKFLOW_WITH_TSC = "jobs:\n  t:\n    steps:\n      - run: bunx tsc --noEmit\n"
WORKFLOW_VIA_SCRIPT = "jobs:\n  t:\n    steps:\n      - run: bun run check\n"


def ctx_for(tmp_path):
    return SimpleNamespace(workdir=tmp_path)


def write_workflow(tmp_path, content):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(content)


def test_compiled_only_repo_skips(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]")
    assert typecheck(ctx_for(tmp_path)).status == Status.SKIP


def test_python_without_typechecker_fails(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    write_workflow(tmp_path, "jobs:\n  t:\n    steps:\n      - run: uv run pytest\n")
    result = typecheck(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "python" in result.details


def test_python_with_mypy_passes(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    write_workflow(tmp_path, "jobs:\n  t:\n    steps:\n      - run: uv run mypy src\n")
    assert typecheck(ctx_for(tmp_path)).status == Status.PASS


def test_untyped_javascript_fails(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    result = typecheck(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "no type layer" in result.details


def test_clojure_with_kondo_passes(tmp_path):
    (tmp_path / "deps.edn").write_text("{}")
    write_workflow(tmp_path, "jobs:\n  t:\n    steps:\n      - run: clj-kondo --lint src\n")
    assert typecheck(ctx_for(tmp_path)).status == Status.PASS


def test_mixed_languages_reports_each_gap(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "pyproject.toml").write_text("[project]")
    write_workflow(tmp_path, WORKFLOW_WITH_TSC)
    result = typecheck(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "python" in result.details and "typescript" not in result.details


def test_ts_without_tsc_in_ci_fails(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}")
    write_workflow(tmp_path, "jobs:\n  t:\n    steps:\n      - run: bun test\n")
    result = typecheck(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "typescript: CI never typechecks" in result.details


def test_tsc_in_workflow_passes(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}")
    write_workflow(tmp_path, WORKFLOW_WITH_TSC)
    assert typecheck(ctx_for(tmp_path)).status == Status.PASS


def test_tsc_hidden_in_package_script_passes(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "package.json").write_text(json.dumps(
        {"scripts": {"check": "biome check src && tsc --noEmit"}}))
    write_workflow(tmp_path, WORKFLOW_VIA_SCRIPT)
    assert typecheck(ctx_for(tmp_path)).status == Status.PASS

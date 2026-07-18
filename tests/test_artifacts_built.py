from types import SimpleNamespace

from conftest import write_wf

from housekeeper.checks.artifacts_built import artifacts_built
from housekeeper.config import Config
from housekeeper.languages import ARTIFACTS
from housekeeper.registry import Status


def ctx_for(tmp_path, artifacts):
    return SimpleNamespace(workdir=tmp_path, artifacts=artifacts, config=Config())


def test_napi_built_directly_passes(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: napi build --release\n",
    )
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["napi"]]))
    assert result.status == Status.PASS
    assert "napi" in result.details


def test_napi_via_nested_bun_run_build_passes(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n"
        "      - run: cd crates/x-node && bun run build\n",
    )
    pkg = tmp_path / "crates" / "x-node"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"scripts":{"build":"napi build --release"}}')
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["napi"]]))
    assert result.status == Status.PASS
    assert "napi" in result.details


def test_site_via_transitive_nested_scripts_passes(tmp_path):
    # CI runs `bun run build:compile`, whose body runs `bun run build:web`,
    # which is the actual browser bundler two scripts deep (the powdermonkey case).
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: bun run build:compile\n",
    )
    (tmp_path / "package.json").write_text(
        '{"scripts":{'
        '"build:web":"bun build src/web/main.tsx --outdir public --target browser",'
        '"build:compile":"bun run build:web && bun build --compile bin/app.ts"}}'
    )
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["site"]]))
    assert result.status == Status.PASS
    assert "site" in result.details


def test_wheel_built_with_maturin_passes(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: maturin develop\n",
    )
    assert (
        artifacts_built(ctx_for(tmp_path, [ARTIFACTS["wheel"]])).status == Status.PASS
    )


def test_wheel_with_no_maturin_fails(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: cargo test\n",
    )
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["wheel"]]))
    assert result.status == Status.FAIL
    assert "wheel" in result.details


def test_tauri_heavy_needs_scheduled_workflow(tmp_path):
    # tauri build on a push-only workflow does not satisfy a heavy artifact.
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: tauri build\n",
    )
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["tauri"]]))
    assert result.status == Status.FAIL
    assert "scheduled" in result.details


def test_tauri_heavy_on_scheduled_workflow_passes(tmp_path):
    write_wf(
        tmp_path,
        "nightly.yml",
        "on:\n  schedule:\n    - cron: '0 0 * * *'\n"
        "jobs:\n  b:\n    steps:\n      - run: tauri build\n",
    )
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["tauri"]]))
    assert result.status == Status.PASS
    assert "tauri" in result.details


def test_site_built_with_vite_passes(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: vite build\n",
    )
    assert artifacts_built(ctx_for(tmp_path, [ARTIFACTS["site"]])).status == Status.PASS


def test_site_with_nothing_fails(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "on: [push]\njobs:\n  b:\n    steps:\n      - run: uv run pytest\n",
    )
    result = artifacts_built(ctx_for(tmp_path, [ARTIFACTS["site"]]))
    assert result.status == Status.FAIL
    assert "site" in result.details.lower()


def test_no_artifacts_skips(tmp_path):
    result = artifacts_built(ctx_for(tmp_path, []))
    assert result.status == Status.SKIP

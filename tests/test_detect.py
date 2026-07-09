"""Detection substrate: artifacts, ecosystem recommends, typed languages, and the
CLI payload builder — all driven directly with a tmp_path, no network/gh."""

from __future__ import annotations

import json

from housekeeper.cli import _detection_payload
from housekeeper.languages import (
    detect_artifacts,
    detect_ecosystems,
    detect_typed_languages,
)


def write(tmp_path, rel, text):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def names(tmp_path):
    return {a.name for a in detect_artifacts(tmp_path)}


def test_napi_addon(tmp_path):
    write(
        tmp_path,
        "crates/foo-node/package.json",
        json.dumps({"devDependencies": {"@napi-rs/cli": "^2"}}),
    )
    assert "napi" in names(tmp_path)


def test_wheel_maturin(tmp_path):
    write(
        tmp_path,
        "crates/foo-python/pyproject.toml",
        '[build-system]\nbuild-backend = "maturin"\n',
    )
    assert "wheel" in names(tmp_path)


def test_gem_extconf(tmp_path):
    write(
        tmp_path,
        "crates/foo-ruby/extconf.rb",
        'require "mkmf"\ncreate_rust_makefile("foo")\n',
    )
    assert "gem" in names(tmp_path)


def test_tauri_app(tmp_path):
    write(tmp_path, "src-tauri/tauri.conf.json", "{}")
    write(tmp_path, "src-tauri/Cargo.toml", '[package]\nname = "app"\n')
    detected = {a.name for a in detect_artifacts(tmp_path)}
    assert "tauri" in detected
    tauri = next(a for a in detect_artifacts(tmp_path) if a.name == "tauri")
    assert tauri.heavy is True


def test_site_bundle(tmp_path):
    write(
        tmp_path,
        "package.json",
        json.dumps({"scripts": {"build": "tsc --noEmit && vite build"}}),
    )
    assert "site" in names(tmp_path)


def test_site_bun_browser_bundle_under_build_web(tmp_path):
    # powdermonkey ships its web bundle as a `build:web` script using Bun's own
    # bundler (`bun build ... --target browser`), not a named site tool.
    write(
        tmp_path,
        "package.json",
        json.dumps(
            {"scripts": {"build:web": "bun build src/web/main.tsx --target browser"}}
        ),
    )
    assert "site" in names(tmp_path)


def test_bun_compile_is_binary_not_site(tmp_path):
    write(
        tmp_path,
        "package.json",
        json.dumps(
            {"scripts": {"build:compile": "bun build --compile bin/x.ts --outfile x"}}
        ),
    )
    detected = names(tmp_path)
    assert "binary" in detected
    assert "site" not in detected


def test_rust_binary_via_bin_table(tmp_path):
    write(tmp_path, "Cargo.toml", '[package]\nname = "x"\n\n[[bin]]\nname = "x"\n')
    assert "binary" in names(tmp_path)


def test_rust_binary_via_main_rs(tmp_path):
    write(tmp_path, "Cargo.toml", '[package]\nname = "x"\n')
    write(tmp_path, "src/main.rs", "fn main() {}\n")
    assert "binary" in names(tmp_path)


def test_bun_compiled_binary(tmp_path):
    write(
        tmp_path,
        "package.json",
        json.dumps(
            {"scripts": {"compile": "bun build --compile bin/x.ts --outfile dist/x"}}
        ),
    )
    assert "binary" in names(tmp_path)


def test_site_dir_without_package_json_is_not_a_site(tmp_path):
    # a site/ dir carrying only a config file, no package.json -> no "site"
    write(tmp_path, "site/biome.base.json", "{}")
    assert "site" not in names(tmp_path)


def test_vendored_napi_dep_is_pruned(tmp_path):
    write(
        tmp_path,
        "node_modules/dep/package.json",
        json.dumps({"devDependencies": {"@napi-rs/cli": "^2"}}),
    )
    assert "napi" not in names(tmp_path)


def test_empty_repo(tmp_path):
    assert detect_artifacts(tmp_path) == []


def test_cargo_recommends_mentions_lockfiles(tmp_path):
    write(tmp_path, "Cargo.toml", '[package]\nname = "x"\n')
    ecos = detect_ecosystems(tmp_path)
    cargo = next(e for e in ecos if e.name == "cargo")
    assert cargo.recommends
    assert any("lockfiles" in r for r in cargo.recommends)


def test_typed_languages_typescript(tmp_path):
    write(tmp_path, "tsconfig.json", "{}")
    assert detect_typed_languages(tmp_path) == ["typescript"]


def test_typed_languages_python(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    assert "python" in detect_typed_languages(tmp_path)


def test_detection_payload(tmp_path):
    write(tmp_path, "Cargo.toml", '[package]\nname = "x"\n\n[[bin]]\nname = "x"\n')
    write(
        tmp_path,
        "crates/foo-node/package.json",
        json.dumps({"devDependencies": {"@napi-rs/cli": "^2"}}),
    )
    payload = _detection_payload(tmp_path)
    eco_names = {e["name"] for e in payload["ecosystems"]}
    assert "cargo" in eco_names
    art_names = {a["name"] for a in payload["artifacts"]}
    assert "napi" in art_names
    cargo = next(e for e in payload["ecosystems"] if e["name"] == "cargo")
    assert cargo["recommends"]

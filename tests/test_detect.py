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


def test_nested_ecosystems_per_location(tmp_path):
    # A Rust workspace (one root Cargo.lock) with a node package and a python
    # package under crates/ — detection is nested-aware and stamps each dir.
    write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
    write(tmp_path, "Cargo.lock", "# lock\n")
    write(tmp_path, "crates/x-core/Cargo.toml", '[package]\nname = "x-core"\n')
    write(tmp_path, "crates/x-node/package.json", "{}")
    write(tmp_path, "crates/x-node/bun.lock", "")
    write(tmp_path, "crates/x-python/pyproject.toml", "[project]\nname = 'x'\n")
    pairs = {(e.name, e.dir) for e in detect_ecosystems(tmp_path)}
    assert ("cargo", "") in pairs
    assert ("bun", "crates/x-node") in pairs
    assert ("uv", "crates/x-python") in pairs
    # A workspace member carrying only a Cargo.toml does NOT add a cargo instance:
    # the workspace shares the single root Cargo.lock.
    assert [e for e in detect_ecosystems(tmp_path) if e.name == "cargo"] == [
        e for e in detect_ecosystems(tmp_path) if e.name == "cargo" and e.dir == ""
    ]
    assert sum(1 for e in detect_ecosystems(tmp_path) if e.name == "cargo") == 1


def test_lockless_rust_repo_flags_topmost_cargo_toml(tmp_path):
    # No Cargo.lock anywhere, but a Cargo.toml at the root -> still flagged, once.
    write(tmp_path, "Cargo.toml", '[package]\nname = "x"\n')
    write(tmp_path, "crates/y/Cargo.toml", '[package]\nname = "y"\n')
    cargo = [e for e in detect_ecosystems(tmp_path) if e.name == "cargo"]
    assert len(cargo) == 1
    assert cargo[0].dir == ""


def test_nested_manager_picked_by_sibling_lock(tmp_path):
    # Each package.json picks its manager by the lockfile in its OWN directory.
    write(tmp_path, "package.json", "{}")
    write(tmp_path, "bun.lock", "")
    write(tmp_path, "web/package.json", "{}")
    write(tmp_path, "web/pnpm-lock.yaml", "")
    by_dir = {e.dir: e.name for e in detect_ecosystems(tmp_path) if e.language == "js"}
    assert by_dir == {"": "bun", "web": "pnpm"}


def test_detection_is_sorted_and_stable(tmp_path):
    write(tmp_path, "b/package.json", "{}")
    write(tmp_path, "b/bun.lock", "")
    write(tmp_path, "a/package.json", "{}")
    write(tmp_path, "a/bun.lock", "")
    ecos = detect_ecosystems(tmp_path)
    keys = [(e.name, e.dir) for e in ecos]
    assert keys == sorted(keys)


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
    assert cargo["dir"] == ""
    # the nested node package surfaces its directory in the payload
    node = next(e for e in payload["ecosystems"] if e["dir"] == "crates/foo-node")
    assert node["language"] == "js"

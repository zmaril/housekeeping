"""pinned-versions: floating specifiers flagged per detected ecosystem.

Fixtures write a real manifest into tmp_path so `detect_ecosystems` picks the
ecosystem up, then assert on status + the details/note the check produced.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from conftest import write_wf

from housekeeper.checks.pinned_versions import pinned_versions
from housekeeper.config import Config
from housekeeper.languages import detect_ecosystems
from housekeeper.registry import Status


def ctx(tmp_path: Path, overrides: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        workdir=tmp_path,
        config=Config(overrides),
        ecosystems=detect_ecosystems(tmp_path),
    )


# ---- npm / bun ---------------------------------------------------------------


def test_npm_caret_fails(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^1.2.3"}}')
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "npm/bun" in result.details
    assert "react ^1.2.3" in result.details


def test_npm_exact_passes(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "1.2.3"}}')
    assert pinned_versions(ctx(tmp_path)).status == Status.PASS


def test_npm_local_file_dep_excluded(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"x": "1.2.3", "@me/node": "file:../x"}}'
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "@me/node" not in result.details


def test_npm_peer_deps_not_flagged_but_noted(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"x": "1.2.3"}, "peerDependencies": {"react": ">=18"}}'
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "peerDependencies" in result.note


# ---- python ------------------------------------------------------------------


def test_python_lower_bound_fails(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["requests>=2"]\n'
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "python" in result.details


def test_python_exact_passes(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["requests==2.31.0"]\n'
    )
    assert pinned_versions(ctx(tmp_path)).status == Status.PASS


def test_python_capped_range_floating_by_default(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["maturin>=1.7,<2.0"]\n'
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "bounded" in result.note


def test_python_capped_range_ok_with_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["maturin>=1.7,<2.0"]\n'
    )
    result = pinned_versions(ctx(tmp_path, {"pinned-versions": {"capped_ok": True}}))
    assert result.status == Status.PASS
    assert "bounded" in result.note


# ---- ruby --------------------------------------------------------------------


def test_ruby_tilde_fails(tmp_path):
    (tmp_path / "Gemfile").write_text(
        'source "https://rubygems.org"\ngem "rails", "~> 7"\n'
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "ruby" in result.details


def test_ruby_exact_passes(tmp_path):
    (tmp_path / "Gemfile").write_text('gem "rails", "= 7.1.0"\n')
    assert pinned_versions(ctx(tmp_path)).status == Status.PASS


def test_ruby_path_gem_excluded(tmp_path):
    (tmp_path / "Gemfile").write_text(
        'gem "rails", "= 7.1.0"\ngem "local", path: "../local"\n'
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "local" not in result.details


# ---- cargo (advisory) --------------------------------------------------------

CARGO_FLOATING = '[package]\nname = "x"\n[dependencies]\nserde = "1"\n'


def test_cargo_floating_advisory_by_default(tmp_path):
    (tmp_path / "Cargo.toml").write_text(CARGO_FLOATING)
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "cargo" in result.note and "advisory" in result.note


def test_cargo_on_fails(tmp_path):
    (tmp_path / "Cargo.toml").write_text(CARGO_FLOATING)
    result = pinned_versions(ctx(tmp_path, {"pinned-versions": {"cargo": "on"}}))
    assert result.status == Status.FAIL
    assert "cargo" in result.details


def test_cargo_path_and_workspace_and_git_rev(tmp_path):
    sha = "5c65e8f70245fa1940ac9071cfc12916e149a9d3"
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\n'
        "[dependencies]\n"
        'local = { path = "../local" }\n'
        "inherited = { workspace = true }\n"
        f'fluessig = {{ git = "https://x", rev = "{sha}" }}\n'
    )
    # All three deps are excluded/pinned, so even with cargo enforced it passes.
    result = pinned_versions(ctx(tmp_path, {"pinned-versions": {"cargo": "on"}}))
    assert result.status == Status.PASS


# ---- actions -----------------------------------------------------------------

WF_TAG = (
    "name: ci\non: [push]\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n"
)


def test_actions_floating_tag_fails(tmp_path):
    write_wf(tmp_path, "ci.yml", WF_TAG)
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.FAIL
    assert "actions/checkout@v4" in result.details


def test_actions_sha_passes(tmp_path):
    sha = "1" * 40
    write_wf(
        tmp_path,
        "ci.yml",
        f"name: ci\non: [push]\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@{sha}\n",
    )
    assert pinned_versions(ctx(tmp_path)).status == Status.PASS


def test_actions_channel_not_flagged(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: ci\non: [push]\njobs:\n  t:\n    steps:\n"
        "      - uses: dtolnay/rust-toolchain@stable\n",
    )
    result = pinned_versions(ctx(tmp_path))
    assert result.status == Status.PASS
    assert "channel" in result.note


def test_actions_local_excluded(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: ci\non: [push]\njobs:\n  t:\n    steps:\n      - uses: ./.github/actions/x\n",
    )
    assert pinned_versions(ctx(tmp_path)).status == Status.PASS


def test_actions_disabled(tmp_path):
    # A pinned package.json keeps the repo relevant; actions off means the
    # floating workflow ref is not checked.
    (tmp_path / "package.json").write_text('{"dependencies": {"x": "1.2.3"}}')
    write_wf(tmp_path, "ci.yml", WF_TAG)
    result = pinned_versions(ctx(tmp_path, {"pinned-versions": {"actions": False}}))
    assert result.status == Status.PASS
    assert "actions/checkout" not in result.details


def test_ignore_skips_action(tmp_path):
    write_wf(tmp_path, "ci.yml", WF_TAG)
    result = pinned_versions(
        ctx(tmp_path, {"pinned-versions": {"ignore": ["actions/checkout"]}})
    )
    assert result.status == Status.PASS


# ---- skip --------------------------------------------------------------------


def test_no_manifests_skips(tmp_path):
    assert pinned_versions(ctx(tmp_path)).status == Status.SKIP

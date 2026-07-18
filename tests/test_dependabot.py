"""The dependabot check's per-(ecosystem, directory) coverage model.

Detection is nested-aware, so a package under crates/x-node demands a dependabot
`updates` entry AT that directory, not one at the repo root. These drive the
coverage matcher directly (pure) plus the check end-to-end over a fake API ctx.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from housekeeper.checks.dependabot import (
    UPDATE_TEMPLATE,
    _dir_matches,
    covered_pairs,
    dependabot,
    uncovered,
)
from housekeeper.languages import ECOSYSTEMS
from housekeeper.registry import Status


class OkApiCtx:
    """A ctx whose API reports alerts + security fixes enabled, so only the
    dependabot.yml coverage drives the verdict."""

    repo = "o/r"

    def __init__(self, workdir, ecosystems):
        self.workdir = workdir
        self.ecosystems = list(ecosystems)

    def api(self, path, **kwargs):
        return {"enabled": True}


def write_yml(tmp_path: Path, body: str) -> None:
    github = tmp_path / ".github"
    github.mkdir(exist_ok=True)
    (github / "dependabot.yml").write_text(body)


NESTED_NPM = replace(ECOSYSTEMS["bun"], dir="crates/x-node")


def test_dir_matches_exact_and_globs():
    assert _dir_matches("/", "/")
    assert _dir_matches("/crates/x-node", "/crates/x-node")
    assert _dir_matches("crates/x-node/", "/crates/x-node")  # normalized
    # a trailing /* matches one level down, not deeper
    assert _dir_matches("/crates/*", "/crates/x-node")
    assert not _dir_matches("/crates/*", "/crates/x-node/sub")
    # /** matches any depth
    assert _dir_matches("/crates/**", "/crates/x-node/sub")
    assert not _dir_matches("/crates/x-node", "/crates/y-node")


def test_covered_pairs_reads_directory_and_directories(tmp_path):
    write_yml(
        tmp_path,
        "version: 2\nupdates:\n"
        '  - package-ecosystem: "npm"\n    directory: "/crates/x-node"\n'
        '    schedule: {interval: "weekly"}\n'
        '  - package-ecosystem: "cargo"\n    directories: ["/", "/extra"]\n'
        '    schedule: {interval: "weekly"}\n',
    )
    pairs = covered_pairs(tmp_path / ".github" / "dependabot.yml")
    assert ("npm", "/crates/x-node") in pairs
    assert ("cargo", "/") in pairs
    assert ("cargo", "/extra") in pairs


def test_nested_package_uncovered_fails_naming_dir(tmp_path):
    # dependabot.yml covers npm only at the root; the nested package is uncovered.
    write_yml(
        tmp_path,
        'version: 2\nupdates:\n  - package-ecosystem: "npm"\n'
        '    directory: "/"\n    schedule: {interval: "weekly"}\n',
    )
    ctx = OkApiCtx(tmp_path, [NESTED_NPM])
    result = dependabot(ctx)
    assert result.status == Status.FAIL
    assert "missing coverage" in result.details
    assert "crates/x-node" in result.details


def test_nested_package_covered_passes(tmp_path):
    write_yml(
        tmp_path,
        'version: 2\nupdates:\n  - package-ecosystem: "npm"\n'
        '    directory: "/crates/x-node"\n    schedule: {interval: "weekly"}\n',
    )
    ctx = OkApiCtx(tmp_path, [NESTED_NPM])
    result = dependabot(ctx)
    assert result.status == Status.PASS, result.details


def test_nested_package_covered_by_glob_passes(tmp_path):
    write_yml(
        tmp_path,
        'version: 2\nupdates:\n  - package-ecosystem: "npm"\n'
        '    directories: ["/crates/*"]\n    schedule: {interval: "weekly"}\n',
    )
    ctx = OkApiCtx(tmp_path, [NESTED_NPM])
    result = dependabot(ctx)
    assert result.status == Status.PASS, result.details


def test_uncovered_returns_normalized_pairs():
    # The pair carries the ecosystem's own dependabot id (bun's is "bun") and its
    # normalized directory; nothing covered means both instances are missing.
    ctx = SimpleNamespace(ecosystems=[NESTED_NPM, ECOSYSTEMS["cargo"]])
    missing = uncovered(ctx, set())
    assert ("bun", "/crates/x-node") in missing
    assert ("cargo", "/") in missing


def test_update_template_emits_per_directory():
    rendered = UPDATE_TEMPLATE.format(eco="npm", directory="/crates/x-node")
    assert 'directory: "/crates/x-node"' in rendered
    assert 'package-ecosystem: "npm"' in rendered

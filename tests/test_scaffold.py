"""The scaffold produces a fleet-compliant repo: the clone-only checks pass.

The strong assertion is that a fresh scaffold clears every clone-only check a
human doesn't have to help with. Two are excluded by design and documented as
next steps: `lockfiles` (needs deps installed to generate the lockfile) and the
fleet-managed lint configs (`codespell`/`vale`/`stylelint`, delivered by the
captain, not the scaffold). API/admin checks (branch protection, secret
scanning, ...) can't be graded without a live repo and are equally deferred.
"""

from __future__ import annotations

import subprocess
import tomllib
from types import SimpleNamespace

import pytest

from housekeeper.checks.changelog import changelog
from housekeeper.checks.ci import ci_exists
from housekeeper.checks.codeowners import codeowners
from housekeeper.checks.conventional_commits import documented, enforced_in_ci
from housekeeper.checks.dependabot_automerge import dependabot_automerge
from housekeeper.checks.gitignore import gitignore
from housekeeper.checks.license import license_file
from housekeeper.checks.readme import readme
from housekeeper.checks.reproducible_toolchain import reproducible_toolchain
from housekeeper.checks.scripts import scripts
from housekeeper.checks.straitjacket import straitjacket
from housekeeper.checks.stray_files import stray_files
from housekeeper.checks.stray_todos import stray_todos
from housekeeper.checks.typecheck import typecheck
from housekeeper.config import Config
from housekeeper.languages import detect_ecosystems
from housekeeper.registry import Status
from housekeeper.scaffold import FLAVORS, scaffold

FLAVOR_LIST = sorted(FLAVORS)

# Clone-only checks a fresh scaffold must PASS, keyed to their check function.
PASS_CHECKS = {
    "scripts": scripts,
    "gitignore": gitignore,
    "stray-files": stray_files,
    "readme": readme,
    "changelog": changelog,
    "codeowners": codeowners,
    "ci-exists": ci_exists,
    "reproducible-toolchain": reproducible_toolchain,
    "straitjacket": straitjacket,
    "typecheck": typecheck,
}


def make_scaffold(tmp_path, flavor, private=False, force=False):
    dest = tmp_path / "demo"
    result = scaffold(dest, "demo", flavor, private=private, force=force)
    return dest, result


def ctx_for(dest):
    """The slice of RepoContext the clone-only checks read."""
    config = Config(tomllib.loads((dest / ".housekeeping.toml").read_text()))
    return SimpleNamespace(
        workdir=dest,
        config=config,
        ecosystems=detect_ecosystems(dest),
    )


def git_init(dest):
    """A real git repo so stray-todos (git ls-files) scans the tracked files."""
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)


@pytest.mark.parametrize("flavor", FLAVOR_LIST)
@pytest.mark.parametrize("check_name", sorted(PASS_CHECKS))
def test_clone_only_checks_pass(tmp_path, flavor, check_name):
    dest, _ = make_scaffold(tmp_path, flavor)
    ctx = ctx_for(dest)
    result = PASS_CHECKS[check_name](ctx)
    # typecheck legitimately SKIPS for the compiled rust flavor.
    if check_name == "typecheck" and flavor == "rust":
        assert result.status == Status.SKIP
    else:
        assert result.status == Status.PASS, f"{check_name}/{flavor}: {result.details}"


@pytest.mark.parametrize("flavor", FLAVOR_LIST)
def test_stray_todos_pass_over_tracked_files(tmp_path, flavor):
    dest, _ = make_scaffold(tmp_path, flavor)
    git_init(dest)
    ctx = ctx_for(dest)
    result = stray_todos(ctx)
    assert result.status == Status.PASS, result.details


@pytest.mark.parametrize("flavor", FLAVOR_LIST)
def test_license_and_conventional_clone_parts(tmp_path, flavor):
    """The clone-side of the api-gated license and conventional-commits checks."""
    dest, _ = make_scaffold(tmp_path, flavor)
    assert license_file(dest) is not None
    assert enforced_in_ci(dest)
    assert documented(dest)


@pytest.mark.parametrize("flavor", FLAVOR_LIST)
def test_housekeeping_toml_parses_and_opts_into_fleet(tmp_path, flavor):
    dest, _ = make_scaffold(tmp_path, flavor)
    data = tomllib.loads((dest / ".housekeeping.toml").read_text())
    assert data["fleet"] == "zmaril/powderworks"
    # Fleet-locked keys must NOT be set by the scaffold.
    assert "stray-files" not in data
    assert "stray-todos" not in data
    assert "stray-files" not in data.get("checks", {})
    assert "stray-todos" not in data.get("checks", {})


@pytest.mark.parametrize("flavor", FLAVOR_LIST)
def test_private_softens_website(tmp_path, flavor):
    dest, _ = make_scaffold(tmp_path, flavor, private=True)
    data = tomllib.loads((dest / ".housekeeping.toml").read_text())
    assert data["checks"]["website"] == "off"


def test_scaffold_twice_skips_without_force(tmp_path):
    dest, first = make_scaffold(tmp_path, "python")
    assert first.created and not first.skipped
    # Second run over the same dir: everything already exists, nothing created.
    second = scaffold(dest, "demo", "python")
    assert not second.created
    assert set(second.skipped) == set(first.created)


def test_force_overwrites(tmp_path):
    dest, _ = make_scaffold(tmp_path, "python")
    (dest / "README.md").write_text("# clobbered\n")
    forced = scaffold(dest, "demo", "python", force=True)
    assert "README.md" in forced.created
    assert not forced.skipped
    assert "# demo" in (dest / "README.md").read_text()


def test_readme_has_metadata_markers(tmp_path):
    dest, _ = make_scaffold(tmp_path, "python")
    readme_text = (dest / "README.md").read_text()
    assert (
        "<!-- housekeeper:description One-line description of demo goes here. -->"
        in (readme_text)
    )
    assert "<!-- housekeeper:topics powderworks -->" in readme_text


def test_cmd_new_via_cli(tmp_path):
    """The CLI entry point writes a scaffold under --dir/<name>."""
    from housekeeper.cli import cmd_new

    args = SimpleNamespace(
        name="demo",
        dir=str(tmp_path),
        flavor="rust",
        private=False,
        force=False,
        dependabot_automerge=False,
    )
    assert cmd_new(args) == 0
    dest = tmp_path / "demo"
    assert (dest / "Cargo.toml").is_file()
    assert (dest / ".github" / "workflows" / "housekeeping.yml").is_file()
    assert (dest / "scripts" / "dev.sh").is_file()


def test_dependabot_automerge_flag_writes_workflow_and_opts_in(tmp_path):
    """With --dependabot-automerge: the workflow lands, the config declares the
    intent, and the dependabot-automerge check passes against the scaffold."""
    dest = tmp_path / "demo"
    scaffold(dest, "demo", "python", dependabot_automerge=True)

    workflow = dest / ".github" / "workflows" / "dependabot-automerge.yml"
    assert workflow.is_file()
    text = workflow.read_text()
    assert "dependabot[bot]" in text
    assert "gh pr merge --auto" in text

    data = tomllib.loads((dest / ".housekeeping.toml").read_text())
    assert data["allow-auto-merge"]["enabled"] is True
    assert data["allow-auto-merge"]["dependabot"] is True

    result = dependabot_automerge(ctx_for(dest))
    assert result.status == Status.PASS, result.details


def test_dependabot_automerge_off_by_default(tmp_path):
    """Without the flag: no workflow, no [allow-auto-merge] section, and the
    dependabot-automerge check SKIPS (not opted in). Other clone-only checks
    still pass."""
    dest, _ = make_scaffold(tmp_path, "python")

    assert not (dest / ".github" / "workflows" / "dependabot-automerge.yml").exists()
    data = tomllib.loads((dest / ".housekeeping.toml").read_text())
    assert "allow-auto-merge" not in data

    ctx = ctx_for(dest)
    result = dependabot_automerge(ctx)
    assert result.status == Status.SKIP, result.details

    assert scripts(ctx).status == Status.PASS
    assert readme(ctx).status == Status.PASS


def test_flavor_manifests_present(tmp_path):
    for flavor, marker in (
        ("rust", "Cargo.toml"),
        ("bun", "package.json"),
        ("python", "pyproject.toml"),
    ):
        dest, _ = make_scaffold(tmp_path / flavor, flavor)
        assert (dest / marker).is_file()

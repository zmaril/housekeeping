"""Open source repo that publishes an action links its Marketplace listing."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed, skipped
from .readme import find_readme

MARKETPLACE = "github.com/marketplace/actions/"


def action_file(workdir: Path) -> Path | None:
    for name in ("action.yml", "action.yaml"):
        if (workdir / name).is_file():
            return workdir / name
    return None


def marketplace_slug(action_path: Path) -> str | None:
    try:
        name = (yaml.safe_load(action_path.read_text()) or {}).get("name", "")
    except yaml.YAMLError:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or None


@check("action-badge", needs=("clone", "api"))
def action_badge(ctx: RepoContext):
    action = action_file(ctx.workdir)
    if action is None:
        return skipped("repo doesn't publish an action")
    if ctx.visibility != "public":
        return skipped("private repo — the Marketplace is for open source")
    readme = find_readme(ctx.workdir)
    if readme is None:
        return failed("publishes an action but has no README to badge")
    if MARKETPLACE in readme.read_text(errors="replace"):
        return passed("README links its Marketplace listing")
    return failed(
        "publishes an action but the README has no Marketplace badge",
        note="assumes the action is (or will be) published on the Marketplace",
    )


@fix_for("action-badge")
def fix(ctx: RepoContext):
    from ..fixing import console

    action = action_file(ctx.workdir)
    slug = marketplace_slug(action) if action else None
    if action is None or not slug:
        console.print(
            "[yellow]could not derive a Marketplace slug from action.yml's name[/yellow]"
        )
        return
    name = yaml.safe_load(action.read_text()).get("name")
    badge = (
        f"[![{name} on the GitHub Marketplace]"
        f"(https://img.shields.io/badge/marketplace-{slug.replace('-', '--')}-blue?logo=github)]"
        f"(https://github.com/{MARKETPLACE.split('github.com/')[1]}{slug})"
    )

    def write(workdir: Path) -> list[Path]:
        # The check fails (and this fix runs) even when there's no README at
        # all — mypy caught the crash the original code had here.
        readme = find_readme(workdir) or workdir / "README.md"
        lines = (
            readme.read_text(errors="replace").splitlines() if readme.is_file() else []
        )
        for i, line in enumerate(lines):
            if line.lstrip().startswith("# "):
                lines[i : i + 1] = [line, "", badge]
                break
        else:
            lines[0:0] = [badge, ""]
        readme.write_text("\n".join(lines) + "\n")
        return [readme]

    apply_file_fix(
        ctx,
        "action-badge",
        describe=f"add a Marketplace badge for {slug!r} under the README title",
        why="the badge is one-glance proof the action exists and where to get it — "
        "the README is the storefront",
        write_changes=write,
        commit_message="readme: link the Marketplace listing",
    )

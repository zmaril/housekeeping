"""Scripts live in scripts/, and a dev.sh sets up the basic dev environment.

Shell scripts scattered at the root (or wherever) rot in place and nobody
remembers which one to run. The policy (all of it configurable per repo):
every shell script lives under scripts/, there's a scripts/dev.sh that stands
the basic dev environment up — deps, tooling, whatever "getting started" means
here — and the README points at it so a newcomer finds it. Deliberate keepers
outside scripts/ go in .housekeeping.toml: [scripts] allow = ["install.sh"].

Hidden and vendored directories (.git, .github, .githooks, node_modules, .venv,
…) are never scanned — git hooks belong in .githooks/, not scripts/. Different
systems are different; this is the default, not a verdict.
"""

from __future__ import annotations

from ..context import RepoContext
from ..registry import check, failed, passed
from .readme import find_readme

# Vendored/generated/tooling trees whose .sh files aren't the repo's own.
# Any hidden directory (leading dot) is skipped on top of these.
SKIP_DIRS = {
    "node_modules",
    "vendor",
    "target",
    "dist",
    "build",
    "__pycache__",
}


def stray_scripts(ctx: RepoContext, scripts_dir: str, allow: set[str]) -> list[str]:
    """Shell scripts committed outside scripts/, hidden dirs, and vendor trees."""
    strays = []
    for path in sorted(ctx.workdir.rglob("*.sh")):
        rel = path.relative_to(ctx.workdir)
        parts = rel.parts
        if parts[0] == scripts_dir:
            continue
        if any(part.startswith(".") or part in SKIP_DIRS for part in parts):
            continue
        if rel.as_posix() in allow or path.name in allow:
            continue
        strays.append(rel.as_posix())
    return strays


@check("scripts", needs=("clone",))
def scripts(ctx: RepoContext):
    settings = ctx.config.section("scripts")
    scripts_dir = str(settings.get("dir", "scripts")).strip("/")
    dev_name = str(settings.get("dev", "dev.sh"))
    allow = {str(name) for name in settings.get("allow", [])}

    dev_rel = f"{scripts_dir}/{dev_name}"
    problems = []

    strays = stray_scripts(ctx, scripts_dir, allow)
    if strays:
        problems.append(f"shell scripts outside {scripts_dir}/: {', '.join(strays)}")

    dev_path = ctx.workdir / scripts_dir / dev_name
    if not dev_path.is_file():
        problems.append(f"no {dev_rel} to stand up the dev environment")
    else:
        readme = find_readme(ctx.workdir)
        text = readme.read_text(errors="replace") if readme else ""
        if dev_name not in text:
            problems.append(f"{dev_rel} not mentioned in the README")

    if problems:
        return failed(
            "; ".join(problems),
            note=f"scripts live in {scripts_dir}/, {dev_rel} sets up the dev "
            "environment and the README points at it; deliberate keepers via "
            "[scripts] allow in .housekeeping.toml",
        )
    return passed(f"scripts in {scripts_dir}/, {dev_rel} present and in the README")

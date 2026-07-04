"""Every build target actually runs in CI.

The failure mode (seen live): a repo's `build:web` breaks, but CI only lints
and tests, so merges sail through until someone deploys. Light targets
(bundler builds) run per PR; heavy targets (tauri desktop) need a per-PR
compile check plus a full build on a scheduled workflow.
"""

from __future__ import annotations

import json
import re

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .ci import (
    parse_workflow,
    resolve_package_scripts,
    run_commands,
    triggers,
    workflow_files,
)


def package_scripts(ctx: RepoContext) -> dict[str, str]:
    package = ctx.workdir / "package.json"
    if not package.is_file():
        return {}
    try:
        scripts = json.loads(package.read_text()).get("scripts", {})
    except (json.JSONDecodeError, AttributeError):
        return {}
    return {k: str(v) for k, v in scripts.items()}


def build_script_names(scripts: dict[str, str]) -> list[str]:
    return sorted(
        name
        for name in scripts
        if name == "build" or name.startswith("build:") or name.endswith(":build")
    )


@check("builds", needs=("clone",))
def builds(ctx: RepoContext):
    scripts = package_scripts(ctx)
    build_names = build_script_names(scripts)
    has_tauri = (ctx.workdir / "src-tauri").is_dir() or any(
        "tauri" in scripts.get(name, "") for name in build_names
    )

    light = [n for n in build_names if "tauri" not in scripts.get(n, "")]
    if not light and not has_tauri:
        return skipped(
            "no build targets detected",
            note="package.json build scripts and tauri are what's looked for",
        )

    all_text, scheduled_text = [], []
    for path in workflow_files(ctx.workdir):
        workflow = parse_workflow(path)
        if workflow is None:
            continue
        commands = run_commands(workflow)
        commands += "\n" + resolve_package_scripts(ctx.workdir, commands)
        all_text.append(commands)
        if "schedule" in triggers(workflow):
            scheduled_text.append(commands)
    text = "\n".join(all_text)
    nightly = "\n".join(scheduled_text)

    problems, covered = [], []
    for name in light:
        if re.search(rf"\brun {re.escape(name)}\b", text):
            covered.append(name)
        else:
            problems.append(f"build script {name!r} never runs in CI")

    if has_tauri:
        if re.search(r"tauri build", nightly):
            covered.append("tauri (scheduled full build)")
        else:
            problems.append(
                "tauri: no full build on a scheduled workflow "
                "(heavy targets build nightly/weekly)"
            )
        compile_ok = re.search(
            r"(cargo (check|build|clippy)[^\n]*src-tauri|src-tauri[^\n]*cargo (check|build|clippy)|tauri build --debug)",
            text,
        )
        if compile_ok:
            covered.append("tauri (per-PR compile check)")
        else:
            problems.append("tauri: no per-PR compile check (cargo check on src-tauri)")

    if problems:
        return failed(
            "; ".join(problems),
            note="a build that CI never runs is a build that breaks silently",
        )
    return passed(f"all build targets run in CI: {', '.join(covered)}")

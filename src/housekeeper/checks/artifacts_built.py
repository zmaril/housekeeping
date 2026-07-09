"""artifacts-built: every build artifact a repo produces is built in some workflow.

Detection (languages.py) knows what a repo produces - a napi addon, a wheel, a
gem, a Tauri app, a site bundle, a binary. This check greps the workflows for the
build step each one needs and reports the artifacts with no build coverage. It is
conservative on purpose: it matches step/run text, it does not run anything, so it
warns (recommended) rather than gates. A heavy artifact (a Tauri bundle) is
expected to build on a scheduled workflow; the lighter per-PR gate is the existing
`builds` check's job.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .ci import parse_workflow, run_commands, triggers, workflow_files

RUN_SCRIPT = re.compile(r"\b(?:bun|npm|pnpm|yarn) run ([\w:.-]+)")

_SKIP_DIRS = {"node_modules", "vendor", "target", "dist", "build", "__pycache__"}


def _all_package_scripts(workdir: Path) -> dict[str, str]:
    """Merged scripts from EVERY package.json in the repo (nested included), so a
    `bun run build` that maps to `napi build` in a sub-package is resolvable."""
    merged: dict[str, str] = {}
    for pkg in workdir.rglob("package.json"):
        rel = pkg.relative_to(workdir)
        if any(p.startswith(".") or p in _SKIP_DIRS for p in rel.parts[:-1]):
            continue
        try:
            scripts = json.loads(pkg.read_text(errors="replace")).get("scripts", {})
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(scripts, dict):
            for name, body in scripts.items():
                merged.setdefault(str(name), str(body))
    return merged


def _resolve(commands: str, scripts: dict[str, str]) -> str:
    """Append the bodies of any `<runner> run <name>` referenced in commands,
    following nested `run` references transitively (a `build:compile` script that
    itself runs `build:web`) so a signal two scripts deep is still reachable.
    Cycle-safe: each script is expanded once."""
    seen: set[str] = set()
    pending = [n for n in RUN_SCRIPT.findall(commands) if n in scripts]
    bodies: list[str] = []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        body = scripts[name]
        bodies.append(body)
        pending.extend(n for n in RUN_SCRIPT.findall(body) if n in scripts)
    return "\n".join(bodies)


@check("artifacts-built", needs=("clone",))
def artifacts_built(ctx: RepoContext):
    artifacts = ctx.artifacts
    if not artifacts:
        return skipped(
            "no build artifacts detected",
            note="napi/wheel/gem/tauri/site/binary are what's looked for",
        )
    scripts = _all_package_scripts(ctx.workdir)
    all_text, scheduled_text = [], []
    for path in workflow_files(ctx.workdir):
        workflow = parse_workflow(path)
        if workflow is None:
            continue
        commands = run_commands(workflow)
        commands += "\n" + _resolve(commands, scripts)
        all_text.append(commands)
        if "schedule" in triggers(workflow):
            scheduled_text.append(commands)
    text = "\n".join(all_text)
    scheduled = "\n".join(scheduled_text)

    uncovered, covered = [], []
    for art in artifacts:
        haystack = scheduled if art.heavy else text
        if art.ci_signal.search(haystack):
            covered.append(art.name)
        else:
            where = "a scheduled workflow" if art.heavy else "any workflow"
            uncovered.append(f"{art.label} not built in {where} ({art.guidance})")
    if uncovered:
        return failed(
            "; ".join(uncovered),
            note="an artifact CI never builds is one that breaks silently; "
            "recommended and conservative (matches workflow text, does not run it)",
        )
    return passed(f"every detected artifact builds in CI: {', '.join(covered)}")

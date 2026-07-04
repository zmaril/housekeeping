"""reproducible-toolchain: CI must not build on a floating toolchain version.

`node-version: latest`, `python-version: '*'`, `go-version: latest` — a setup step
that pins to a moving target means the same commit builds differently tomorrow than
today. It bitrots silently: the day the upstream default moves, a green history turns
red for a change nobody made, and "works on my machine" drifts from CI.

We flag `*-version:` (and bare `version:`) values on `setup-*` steps that resolve to
a moving target — `latest`, `*`, or an `x`/`.x` wildcard. Deliberately NOT flagged:
Go's `stable`/`oldstable` (an officially supported channel, not an unbounded latest)
and `dtolnay/rust-toolchain@stable` (Rust's stable channel, the house norm) — those
are bounded, reproducible-enough moving channels, not open `latest`.
"""

from __future__ import annotations

import re

from ..context import RepoContext
from ..registry import check, failed, passed
from .ci import parse_workflow, workflow_files

# A version value that isn't pinned to anything stable: latest, a bare wildcard, or
# an x-style wildcard (18.x, 3.*). `stable`/`oldstable` are intentionally allowed.
FLOATING = re.compile(r"^(?:latest|\*|x|\d+(?:\.\d+)*\.(?:x|\*))$", re.I)


def _version_keys(with_block: dict) -> list[tuple[str, str]]:
    out = []
    for key, value in with_block.items():
        if not isinstance(key, str):
            continue
        if key == "version" or key.endswith("-version"):
            out.append((key, str(value).strip()))
    return out


@check("reproducible-toolchain", needs=("clone",))
def reproducible_toolchain(ctx: RepoContext):
    floating: list[str] = []
    for path in workflow_files(ctx.workdir):
        workflow = parse_workflow(path)
        if not workflow:
            continue
        for jid, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                with_block = step.get("with")
                if not (isinstance(uses, str) and "setup-" in uses) or not isinstance(
                    with_block, dict
                ):
                    continue
                for key, value in _version_keys(with_block):
                    if FLOATING.match(value):
                        floating.append(f"{path.name}: {key}: {value}")
    if floating:
        return failed(
            "CI builds on a floating toolchain version: " + ", ".join(floating),
            note="pin to an explicit version (or a bounded channel like Go's "
            "'stable') so the same commit builds the same way tomorrow",
        )
    return passed("no floating toolchain versions in CI setup steps")

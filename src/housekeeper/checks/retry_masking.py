"""test-retry-masking: auto-rerunning tests until they pass launders flakiness into
a false green.

A retry harness — `pytest --reruns`, `jest --retries`, Playwright `retries`,
nextest `retries` — reruns a failed test and reports success if any attempt passes.
That's the exact anti-pattern of a flaky suite: a real intermittent failure gets
papered over, the signal you'd have investigated is gone, and the bug ships. Retries
have legitimate uses (a genuinely non-deterministic integration boundary), so this
is recommended, not required — except it where you mean it.

Scans CI workflow commands and the usual test-config files for retry mechanisms.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..context import RepoContext
from ..registry import check, failed, passed
from .ci import iter_jobs, step_text

# Retry flags on a test command line (in a workflow `run:` or a script).
COMMAND_RETRY = re.compile(r"--reruns\b|--retries\b|pytest-rerunfailures", re.I)

# (filename, pattern) pairs for retry configuration in the usual config files.
CONFIG_SIGNALS: list[tuple[str, re.Pattern]] = [
    ("pyproject.toml", re.compile(r"reruns|rerunfailures", re.I)),
    ("pytest.ini", re.compile(r"reruns|rerunfailures", re.I)),
    ("tox.ini", re.compile(r"reruns|rerunfailures", re.I)),
    ("setup.cfg", re.compile(r"reruns|rerunfailures", re.I)),
    # A nonzero retry count in a JS/Playwright/nextest config.
    ("playwright.config.ts", re.compile(r"retries\s*:\s*[1-9]")),
    ("playwright.config.js", re.compile(r"retries\s*:\s*[1-9]")),
    ("jest.config.ts", re.compile(r"retryTimes\s*\(\s*[1-9]|retries\s*:\s*[1-9]")),
    ("jest.config.js", re.compile(r"retryTimes\s*\(\s*[1-9]|retries\s*:\s*[1-9]")),
    ("vitest.config.ts", re.compile(r"retry\s*:\s*[1-9]")),
    ("vitest.config.js", re.compile(r"retry\s*:\s*[1-9]")),
    (".config/nextest.toml", re.compile(r"retries\s*=\s*[1-9]")),
]


def _config_hits(workdir: Path) -> list[str]:
    hits = []
    for name, pattern in CONFIG_SIGNALS:
        path = workdir / name
        if path.is_file() and pattern.search(path.read_text(errors="replace")):
            hits.append(name)
    return hits


def _command_hits(workdir: Path) -> list[str]:
    hits = []
    for path, jid, job in iter_jobs(workdir):
        for step in job.get("steps") or []:
            if isinstance(step, dict) and COMMAND_RETRY.search(step_text(step)):
                hits.append(f"{path.name}: {job.get('name') or jid}")
                break
    return hits


@check("test-retry-masking", needs=("clone",))
def retry_masking(ctx: RepoContext):
    hits = _command_hits(ctx.workdir) + _config_hits(ctx.workdir)
    if hits:
        return failed(
            "tests auto-retry, which can mask flakiness: " + ", ".join(sorted(hits)),
            note="a rerun-until-green harness hides intermittent failures — fix the "
            "flake, or except this check in .housekeeping.toml where retries are "
            "deliberate",
        )
    return passed("no rerun-until-green test retry configured")

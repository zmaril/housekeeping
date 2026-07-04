"""ci-continue-on-error: a test/lint/build step must not be allowed to fail silently.

`continue-on-error: true` tells GitHub Actions the step (or job) may fail while the
workflow still reports success — a green check. On a step that runs the tests, the
linter, or the build, that means CI goes green while the thing it exists to catch is
red: the build lies. A whole job marked `continue-on-error` is the same failure a
level up.

We flag it on jobs (always — a job you're willing to let fail wholesale isn't
gating anything) and on steps whose command actually runs tests/lint/build. A step
that legitimately tolerates failure (an optional coverage upload, a flaky external
probe) is the exception, handled the house way: turn the check off, or set its
severity in `.housekeeping.toml`.
"""

from __future__ import annotations

import re

from ..context import RepoContext
from ..registry import check, failed, passed
from .ci import iter_jobs, step_text

# Commands whose failure CI exists to catch. Kept deliberately to unambiguous
# test/lint/build/typecheck invocations so a tolerated side-step isn't swept in.
GATING = re.compile(
    r"\b(?:cargo (?:test|nextest|clippy|build|check)|rustfmt"
    r"|go (?:test|build|vet)|golangci-lint|staticcheck"
    r"|pytest|tox|ruff (?:check|format)|mypy|pyright|black|flake8|pylint"
    r"|bun test|npm test|pnpm test|yarn test|vitest|jest|playwright"
    r"|eslint|oxlint|biome|prettier|tsc\b|dprint"
    r"|rspec|rubocop|standardrb|bundle exec (?:rake|rspec)"
    r"|gradlew?|mvn|msbuild|dotnet (?:test|build)|xcodebuild|cmake --build)\b",
    re.I,
)


def _is_true(value: object) -> bool:
    # YAML gives us a bool; tolerate the string form too.
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


@check("ci-continue-on-error", needs=("clone",))
def ci_continue_on_error(ctx: RepoContext):
    offenders: list[str] = []
    for path, jid, job in iter_jobs(ctx.workdir):
        label = job.get("name") or jid
        if _is_true(job.get("continue-on-error")):
            offenders.append(f"{path.name}: job '{label}'")
            continue  # the whole job already leaks; don't also list its steps
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            if _is_true(step.get("continue-on-error")) and GATING.search(
                step_text(step)
            ):
                name = step.get("name") or step.get("run") or step.get("uses") or ""
                offenders.append(f"{path.name}: '{name.splitlines()[0][:60]}'")
    if offenders:
        return failed(
            "continue-on-error on gating steps hides failures: " + ", ".join(offenders),
            note="a test/lint/build step marked continue-on-error keeps CI green when "
            "it fails — drop the flag, or if the failure is genuinely tolerable set "
            "checks.ci-continue-on-error in .housekeeping.toml",
        )
    return passed("no test/lint/build step masks its failure with continue-on-error")

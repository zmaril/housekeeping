"""ci-exists: workflows cover test + lint. ci-green: latest default-branch run succeeded."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed, skipped

TEST_PATTERN = re.compile(r"\b(cargo test|bun test|npm test|pytest|go test|test)\b")
LINT_PATTERN = re.compile(r"\b(clippy|ruff|eslint|lint|cargo fmt|rustfmt|prettier|biome)\b")


def workflow_files(workdir: Path) -> list[Path]:
    workflows = workdir / ".github" / "workflows"
    return sorted(workflows.glob("*.y*ml")) if workflows.is_dir() else []


def parse_workflow(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def triggers(workflow: dict) -> set[str]:
    # YAML 1.1 parses bare `on` as the boolean True.
    on = workflow.get("on", workflow.get(True, {}))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on.keys())
    return set()


def run_commands(workflow: dict) -> str:
    """All run: strings and uses: refs, concatenated for signal matching."""
    chunks = []
    for job in (workflow.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            for key in ("run", "uses", "name"):
                if isinstance(step.get(key), str):
                    chunks.append(step[key])
    return "\n".join(chunks).lower()


@check("ci-exists", needs=("clone",))
def ci_exists(ctx: RepoContext):
    files = workflow_files(ctx.workdir)
    if not files:
        return failed("no workflows in .github/workflows/")

    triggered, all_commands = False, []
    for path in files:
        workflow = parse_workflow(path)
        if workflow is None:
            return failed(f"{path.name} is not valid YAML")
        if {"push", "pull_request"} & triggers(workflow):
            triggered = True
            all_commands.append(run_commands(workflow))
    commands = "\n".join(all_commands)

    problems = []
    if not triggered:
        problems.append("no workflow triggers on push/pull_request")
    if not TEST_PATTERN.search(commands):
        problems.append("no test step found")
    if not LINT_PATTERN.search(commands):
        problems.append("no lint step found")
    if problems:
        return failed("; ".join(problems))
    return passed(f"{len(files)} workflow(s) with test + lint, triggered on push/PR")


CI_TEMPLATES = {
    "cargo": (
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: dtolnay/rust-toolchain@stable\n"
        "        with: {components: 'clippy, rustfmt'}\n"
        "      - run: cargo fmt --check\n"
        "      - run: cargo clippy -- -D warnings\n"
        "      - run: cargo test\n"
    ),
    "bun": (
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: oven-sh/setup-bun@v2\n"
        "      - run: bun install --frozen-lockfile\n"
        "      - run: bun run lint\n"
        "      - run: bun test\n"
    ),
    "uv": (
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: astral-sh/setup-uv@v5\n"
        "      - run: uv sync\n"
        "      - run: uv run ruff check .\n"
        "      - run: uv run pytest\n"
    ),
    "go": (
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-go@v5\n"
        "      - run: gofmt -l . && test -z \"$(gofmt -l .)\"\n"
        "      - run: go vet ./...\n"
        "      - run: go test ./...\n"
    ),
}


@fix_for("ci-exists")
def fix(ctx: RepoContext):
    jobs = [CI_TEMPLATES[e.name] for e in ctx.ecosystems if e.name in CI_TEMPLATES]
    if not jobs:
        from ..fixing import console
        console.print("[yellow]no ecosystem with a CI template detected — write the workflow by hand[/yellow]")
        return
    content = "name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\n\njobs:\n" + "\n".join(jobs)

    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "ci.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return [target]

    apply_file_fix(
        ctx, "ci-exists",
        describe="scaffold .github/workflows/ci.yml with test + lint jobs "
                 f"for: {', '.join(e.name for e in ctx.ecosystems if e.name in CI_TEMPLATES)}",
        why="without CI, broken code merges silently — a push/PR workflow catches "
            "failures before they land on main, and gives branch protection status "
            "checks to require",
        write_changes=write,
        commit_message="ci: add test + lint workflow",
    )


@check("ci-green", needs=("api",))
def ci_green(ctx: RepoContext):
    """Latest completed default-branch run of EVERY repo workflow must be green.

    The runs list also contains workflows GitHub operates inside the repo
    (Dependabot Updates, Dependency Graph — path starts with "dynamic/").
    Grading "the latest run overall" can grade one of those, or grade one
    workflow while another sits red, so: filter to workflows that actually
    live in .github/workflows/ and require all of them to pass.

    When running INSIDE a workflow (the housekeeping action), that workflow
    grades itself one run behind: one transient red and every later run fails
    because the previous one did, forever. Exclude the hosting workflow.
    """
    hosting = os.environ.get("GITHUB_WORKFLOW")
    workflows = ctx.api(f"repos/{ctx.repo}/actions/workflows").get("workflows", [])
    real = [w for w in workflows
            if w.get("path", "").startswith(".github/workflows/")
            and w.get("state") == "active"
            and w.get("name") != hosting]
    if not real:
        return skipped("no workflows", note="ci-exists covers the absence of CI")

    red, green, quiet = [], [], []
    for workflow in real:
        runs = ctx.api(
            f"repos/{ctx.repo}/actions/workflows/{workflow['id']}/runs",
            params={"branch": ctx.default_branch, "status": "completed", "per_page": 1},
        )
        latest = (runs.get("workflow_runs") or [None])[0]
        if latest is None:
            quiet.append(workflow["name"])
        elif latest.get("conclusion") == "success":
            green.append(workflow["name"])
        else:
            red.append(f"{workflow['name']} ({latest.get('conclusion')}: {latest.get('html_url', '')})")

    notes = []
    if quiet:
        notes.append(f"no completed {ctx.default_branch} runs yet for: {', '.join(quiet)}")
    if hosting and any(w.get("name") == hosting for w in workflows):
        notes.append(f"not grading {hosting!r} — this check runs inside it")
    note = "; ".join(notes)
    if red:
        return failed(f"red on {ctx.default_branch}: {'; '.join(red)}", note)
    if not green:
        return skipped(f"no workflow has a completed {ctx.default_branch} run yet", note)
    return passed(f"latest {ctx.default_branch} runs green: {', '.join(green)}", note)

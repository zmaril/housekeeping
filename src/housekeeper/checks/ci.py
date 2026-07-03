"""ci-exists: workflows cover test + lint. ci-green: latest default-branch run succeeded."""

from __future__ import annotations

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
    runs = ctx.api(f"repos/{ctx.repo}/actions/runs",
                   params={"branch": ctx.default_branch, "per_page": 1})
    if not runs.get("workflow_runs"):
        return skipped(f"no workflow runs on {ctx.default_branch}",
                       note="fails ci-exists instead if there's no CI at all")
    latest = runs["workflow_runs"][0]
    name, conclusion = latest.get("name", "?"), latest.get("conclusion")
    if latest.get("status") != "completed":
        return skipped(f"latest run of {name!r} still {latest.get('status')}")
    if conclusion == "success":
        return passed(f"latest {ctx.default_branch} run of {name!r} succeeded")
    return failed(f"latest {ctx.default_branch} run of {name!r}: {conclusion}",
                  note=latest.get("html_url", ""))

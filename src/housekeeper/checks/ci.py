"""ci-exists: every detected language has its own test/lint/fmt steps in CI.
ci-green: latest default-branch run of every workflow succeeded.

A repo with rust + ruby + python bindings whose CI only tests the rust half
is the failure mode: green CI, untested languages. Signals are matched per
language, and combined tools (biome, rubocop) legitimately satisfy both lint
and fmt for theirs."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed, skipped

PACKAGE_SCRIPT = re.compile(r"\b(?:bun|npm|pnpm|yarn) run ([\w:.-]+)")

LANGUAGE_OF = {
    "cargo": "rust",
    "bun": "js",
    "npm": "js",
    "pnpm": "js",
    "yarn": "js",
    "uv": "python",
    "pip": "python",
    "ruby": "ruby",
    "go": "go",
}

LANG_SIGNALS: dict[str, dict[str, re.Pattern]] = {
    "rust": {
        "test": re.compile(r"\bcargo (nextest|test)\b"),
        "lint": re.compile(r"\bclippy\b"),
        "fmt": re.compile(r"\b(cargo fmt|rustfmt)\b"),
    },
    "js": {
        "test": re.compile(
            r"\b(bun test|npm test|pnpm test|yarn test|vitest|jest|playwright)\b"
        ),
        "lint": re.compile(r"\b(eslint|oxlint|biome (check|lint|ci))\b"),
        "fmt": re.compile(r"\b(prettier|dprint|biome (check|format|ci))\b"),
    },
    "python": {
        "test": re.compile(r"\b(pytest|python -m unittest|tox)\b"),
        "lint": re.compile(r"\b(ruff check|flake8|pylint)\b"),
        "fmt": re.compile(r"\b(ruff format|black)\b"),
    },
    "ruby": {
        "test": re.compile(r"\b(rspec|rake (test|spec)|minitest)\b"),
        "lint": re.compile(r"\b(rubocop|standardrb)\b"),
        "fmt": re.compile(r"\b(rubocop|standardrb)\b"),
    },
    "go": {
        "test": re.compile(r"\bgo test\b"),
        "lint": re.compile(r"\b(go vet|golangci-lint|staticcheck)\b"),
        "fmt": re.compile(r"\b(gofmt|gofumpt)\b"),
    },
}


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


def resolve_package_scripts(workdir: Path, commands: str) -> str:
    """A workflow's `bun run check` can hide the actual linter inside
    package.json scripts — resolve one level so the patterns can see it."""
    package = workdir / "package.json"
    if not package.is_file():
        return ""
    try:
        scripts = json.loads(package.read_text()).get("scripts", {})
    except (json.JSONDecodeError, AttributeError):
        return ""
    bodies = [
        str(scripts[name])
        for name in PACKAGE_SCRIPT.findall(commands)
        if name in scripts
    ]
    return "\n".join(bodies).lower()


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
    commands += "\n" + resolve_package_scripts(ctx.workdir, commands)

    problems = []
    if not triggered:
        problems.append("no workflow triggers on push/pull_request")

    languages = sorted(
        {LANGUAGE_OF[e.name] for e in ctx.ecosystems if e.name in LANGUAGE_OF}
    )
    for lang in languages:
        for signal, pattern in LANG_SIGNALS[lang].items():
            if not pattern.search(commands):
                problems.append(f"{lang}: no {signal} step")
    if problems:
        return failed("; ".join(problems))
    if not languages:
        return passed(
            f"{len(files)} workflow(s) triggered on push/PR",
            note="no language ecosystems detected to demand jobs for",
        )
    return passed(f"test + lint + fmt in CI for every language: {', '.join(languages)}")


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
        "      - run: uv run ruff format --check .\n"
        "      - run: uv run pytest\n"
    ),
    "ruby": (
        "  ruby:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: ruby/setup-ruby@v1\n"
        "        with: {bundler-cache: true}\n"
        "      - run: bundle exec rubocop\n"
        "      - run: bundle exec rake test\n"
    ),
    "go": (
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-go@v5\n"
        '      - run: gofmt -l . && test -z "$(gofmt -l .)"\n'
        "      - run: go vet ./...\n"
        "      - run: go test ./...\n"
    ),
}


@fix_for("ci-exists")
def fix(ctx: RepoContext):
    jobs = [CI_TEMPLATES[e.name] for e in ctx.ecosystems if e.name in CI_TEMPLATES]
    if not jobs:
        from ..fixing import console

        console.print(
            "[yellow]no ecosystem with a CI template detected — write the workflow by hand[/yellow]"
        )
        return
    content = (
        "name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\n\njobs:\n"
        + "\n".join(jobs)
    )

    def write(workdir: Path) -> list[Path]:
        target = workdir / ".github" / "workflows" / "ci.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return [target]

    apply_file_fix(
        ctx,
        "ci-exists",
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

    Housekeeping-family workflows (the self-audit, the fleet captain) are
    excluded by name for the same reason one level up: on a repo carrying
    both, each grades the other and a single red deadlocks the pair — red
    because the other is red, forever. The family audits the repo; ci-green
    grades the repo's OWN CI. The captain grades the self-audit explicitly,
    and a red captain is its own alarm.
    """
    hosting = os.environ.get("GITHUB_WORKFLOW")
    family = {"housekeeping", "housecaptain"}
    workflows = ctx.api(f"repos/{ctx.repo}/actions/workflows").get("workflows", [])
    real = [
        w
        for w in workflows
        if w.get("path", "").startswith(".github/workflows/")
        and w.get("state") == "active"
        and w.get("name") != hosting
        and w.get("name") not in family
    ]
    excluded = sorted(
        {
            w.get("name", "")
            for w in workflows
            if w.get("name") in family or w.get("name") == hosting
        }
    )
    if not real:
        return skipped(
            "no workflows to grade beyond housekeeping's own",
            note="not grading housekeeping-family/hosting workflows: "
            + ", ".join(excluded)
            if excluded
            else "ci-exists covers the absence of CI",
        )

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
            red.append(
                f"{workflow['name']} ({latest.get('conclusion')}: {latest.get('html_url', '')})"
            )

    notes = []
    if quiet:
        notes.append(
            f"no completed {ctx.default_branch} runs yet for: {', '.join(quiet)}"
        )
    if excluded:
        notes.append(
            f"not grading housekeeping-family/hosting workflows: {', '.join(excluded)}"
        )
    note = "; ".join(notes)
    if red:
        return failed(f"red on {ctx.default_branch}: {'; '.join(red)}", note)
    if not green:
        return skipped(
            f"no workflow has a completed {ctx.default_branch} run yet", note
        )
    return passed(f"latest {ctx.default_branch} runs green: {', '.join(green)}", note)

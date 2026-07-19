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
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path

import yaml

from ..context import RepoContext
from ..fixing import apply_file_fix
from ..languages import LANGUAGES
from ..registry import check, failed, fix_for, passed, skipped

PACKAGE_SCRIPT = re.compile(r"\b(?:bun|npm|pnpm|yarn) run ([\w:.-]+)")

# Test/lint/fmt signals and CI templates now live in languages.py — a check reads
# `eco.language` / `LANGUAGES[...]` / `eco.ci_template` instead of a table here.
SIGNAL_NAMES = ("test", "lint", "fmt")


def _label(eco) -> str:
    """The ecosystem's name, tagged with its directory when it isn't the root, so an
    exemption line reads `bun (spike)` for a nested package — mirrors lockfiles."""
    return f"{eco.name} ({eco.dir})" if eco.dir else eco.name


def _ignored(rel: str, ignore: list[str]) -> bool:
    """Prefix/glob match, mirroring stray_todos._ignored: `ignore = ["spikes"]`
    exempts `spikes` AND `spikes/foo` (throwaway trees often hold nested packages)."""
    for pat in ignore:
        p = pat.strip("/")
        if fnmatch(rel, p) or fnmatch(rel, f"{p}/*"):
            return True
    return False


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


def workflows(workdir: Path) -> Iterator[tuple[Path, dict]]:
    """Every `(path, parsed workflow)` — the shared walk, so no CI check re-opens
    and re-parses the workflow directory by hand."""
    for path in workflow_files(workdir):
        workflow = parse_workflow(path)
        if workflow:
            yield path, workflow


def iter_jobs(workdir: Path) -> Iterator[tuple[Path, str, dict]]:
    """Every `(workflow path, job id, job dict)` across all workflows."""
    for path, workflow in workflows(workdir):
        for jid, job in (workflow.get("jobs") or {}).items():
            if isinstance(job, dict):
                yield path, jid, job


def step_text(step: dict) -> str:
    """A step's `run` / `uses` / `name` strings joined, for signal matching."""
    return "\n".join(
        step[key] for key in ("run", "uses", "name") if isinstance(step.get(key), str)
    )


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

    # A repo can exempt throwaway/scratch package directories (a spike, a
    # generated demo) from the per-language CI demand — mirrors [lockfiles] ignore:
    #   [ci-exists]
    #   ignore = ["spike", "typespec"]
    # Matching is prefix/glob (like stray-todos), so `ignore = ["spikes"]` exempts
    # `spikes` AND `spikes/foo`. A language leaves the demand set only when EVERY
    # instance carrying it is exempt: an exempt scratch package must not excuse a
    # real package of the same language elsewhere.
    ignore = [str(p) for p in ctx.config.section("ci-exists").get("ignore", [])]
    kept, exempt = [], []
    for eco in ctx.ecosystems:
        if _ignored(str(eco.dir).strip("/"), ignore):
            exempt.append(eco)
        else:
            kept.append(eco)
    exempt_labels = [_label(e) for e in exempt if e.language]
    note = (
        f"not graded: {', '.join(exempt_labels)} (exempt via [ci-exists] ignore)"
        if exempt_labels
        else ""
    )

    languages = sorted({e.language for e in kept if e.language})
    for lang in languages:
        language = LANGUAGES[lang]
        for signal in SIGNAL_NAMES:
            if not getattr(language, signal).search(commands):
                problems.append(f"{lang}: no {signal} step")
    if problems:
        return failed("; ".join(problems), note)
    if not languages:
        return passed(
            f"{len(files)} workflow(s) triggered on push/PR",
            note=note or "no language ecosystems detected to demand jobs for",
        )
    return passed(
        f"test + lint + fmt in CI for every language: {', '.join(languages)}",
        note,
    )


def templated_ecosystems(ecosystems) -> list:
    """Ecosystems with a CI template, deduped by name: nested instances of the same
    ecosystem (a repo with several crates/*-node bun packages) share one CI job
    template, not one scaffolded job per copy."""
    seen: set[str] = set()
    out = []
    for e in ecosystems:
        if e.ci_template and e.name not in seen:
            seen.add(e.name)
            out.append(e)
    return out


@fix_for("ci-exists")
def fix(ctx: RepoContext):
    from ..fixing import console

    # ci-exists fails two very different ways: no CI at all, or CI that exists but
    # is missing a test/lint/fmt step. Scaffolding only answers the first. On a repo
    # that already has workflows it would overwrite a hand-written ci.yml — the
    # exact CI this check is asking to *extend* — so refuse and say what's missing.
    existing = workflow_files(ctx.workdir)
    if existing:
        console.print(
            "[yellow]this repo already has "
            f"{len(existing)} workflow(s): {', '.join(p.name for p in existing)}.[/yellow]\n"
            "Scaffolding ci.yml would overwrite them, so this fix stops here — the "
            "missing steps have to be added to the existing workflow by hand."
        )
        missing = [p for p in ci_exists(ctx).details.split("; ") if " no " in p]
        if missing:
            console.print("\nWhat this repo is missing:")
            for problem in missing:
                console.print(f"  - {problem}")
        return

    templated = templated_ecosystems(ctx.ecosystems)
    if not templated:
        console.print(
            "[yellow]no ecosystem with a CI template detected — write the workflow by hand[/yellow]"
        )
        return
    content = (
        "name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\n\njobs:\n"
        + "\n".join(e.ci_template for e in templated)
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
        f"for: {', '.join(e.name for e in templated)}",
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

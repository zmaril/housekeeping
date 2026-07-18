"""dependabot.yml covers every detected ecosystem; alerts + security updates enabled."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..context import GhError, RepoContext
from ..fixing import apply_file_fix, confirm, console
from ..registry import check, failed, fix_for, passed


def dependabot_path(workdir: Path) -> Path | None:
    for name in ("dependabot.yml", "dependabot.yaml"):
        path = workdir / ".github" / name
        if path.is_file():
            return path
    return None


def _norm_dir(directory: str) -> str:
    """A dependabot `directory` normalized to a leading-slash, no-trailing-slash
    form: "" / "/" -> "/", "crates/x-node/" -> "/crates/x-node"."""
    stripped = directory.strip().strip("/")
    return "/" + stripped if stripped else "/"


def _dir_matches(pattern: str, target: str) -> bool:
    """Does one dependabot `directory`/`directories` entry cover `target` (a
    normalized "/dir")? Supports exact match plus a trailing `/*` (one level) or
    `/**` (any depth) glob, which `directories` lists commonly use (`/crates/*`)."""
    p = pattern.strip()
    if p.endswith("/**"):
        base = _norm_dir(p[:-3])
        prefix = "/" if base == "/" else base + "/"
        return target == base or target.startswith(prefix)
    if p.endswith("/*"):
        base = _norm_dir(p[:-2])
        prefix = "/" if base == "/" else base + "/"
        if not target.startswith(prefix):
            return False
        rest = target[len(prefix) :]
        return rest != "" and "/" not in rest
    return _norm_dir(p) == target


def covered_pairs(path: Path) -> set[tuple[str, str]]:
    """The `(package-ecosystem, directory-pattern)` pairs a dependabot.yml declares.
    Directory patterns are kept RAW (not normalized) so globs survive for matching;
    an entry may carry a single `directory` or a `directories` list."""
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return set()
    pairs: set[tuple[str, str]] = set()
    for u in data.get("updates", []):
        if not isinstance(u, dict):
            continue
        eco = u.get("package-ecosystem", "")
        if not isinstance(eco, str):
            continue
        dirs: list[str] = []
        if isinstance(u.get("directory"), str):
            dirs.append(u["directory"])
        if isinstance(u.get("directories"), list):
            dirs.extend(d for d in u["directories"] if isinstance(d, str))
        for directory in dirs:
            pairs.add((eco, directory))
    return pairs


def uncovered(ctx: RepoContext, covered: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """The `(dependabot-id, normalized-dir)` requirements no dependabot entry covers.
    An ecosystem instance in `crates/x-node` demands coverage AT that directory, not
    the repo root — so a root-only npm entry no longer satisfies a nested package."""
    missing: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for eco in ctx.ecosystems:
        acceptable = {eco.dependabot, *eco.dependabot_alts}
        want = _norm_dir(eco.dir)
        key = (eco.dependabot, want)
        if key in seen:
            continue
        seen.add(key)
        if not any(e in acceptable and _dir_matches(d, want) for (e, d) in covered):
            missing.append(key)
    return sorted(missing)


def _show(pairs: list[tuple[str, str]]) -> str:
    return ", ".join(f"{eid} ({directory})" for eid, directory in pairs)


def _setting(ctx: RepoContext, path: str) -> bool | None:
    """True enabled, False disabled, None if the token can't see it (403)."""
    try:
        result = ctx.api(path)
    except GhError as e:
        if e.status == 404:
            return False
        if e.status == 403:
            return None
        raise
    if isinstance(result, dict):
        return bool(result.get("enabled"))
    return True  # 204-style empty success


@check("dependabot", needs=("clone", "api"))
def dependabot(ctx: RepoContext):
    problems, unknown = [], []
    path = dependabot_path(ctx.workdir)
    if path is None:
        problems.append("no .github/dependabot.yml")
    else:
        missing = uncovered(ctx, covered_pairs(path))
        if missing:
            problems.append(f"dependabot.yml missing coverage: {_show(missing)}")

    for label, api_path in (
        ("vulnerability alerts", f"repos/{ctx.repo}/vulnerability-alerts"),
        ("automated security fixes", f"repos/{ctx.repo}/automated-security-fixes"),
    ):
        state = _setting(ctx, api_path)
        if state is False:
            problems.append(f"{label} disabled")
        elif state is None:
            unknown.append(label)

    note = (
        (
            f"not visible to this token: {', '.join(unknown)} — "
            "run housekeeper locally for full coverage"
        )
        if unknown
        else ""
    )
    if problems:
        return failed("; ".join(problems), note)
    return passed(
        "dependabot.yml covers all ecosystems"
        + ("" if unknown else "; alerts + security fixes on"),
        note,
    )


UPDATE_TEMPLATE = """\
  - package-ecosystem: "{eco}"
    directory: "{directory}"
    schedule:
      interval: "weekly"
"""


@fix_for("dependabot")
def fix(ctx: RepoContext):
    # API-side settings first — cheap, reversible, no commit needed.
    if ctx.try_api(f"repos/{ctx.repo}/vulnerability-alerts") is None:
        console.print(
            "\nVulnerability alerts: GitHub checks your dependency graph against its "
            "advisory database and notifies you when something you depend on has a "
            "known CVE — otherwise you find out from the incident."
        )
        if confirm(f"Enable vulnerability alerts on {ctx.repo}?"):
            ctx.api(f"repos/{ctx.repo}/vulnerability-alerts", method="PUT")
            console.print("[green]vulnerability alerts enabled[/green]")
    fixes_state = ctx.try_api(f"repos/{ctx.repo}/automated-security-fixes")
    if not (isinstance(fixes_state, dict) and fixes_state.get("enabled")):
        console.print(
            "\nAutomated security fixes: when an alert fires, Dependabot opens a PR "
            "bumping the vulnerable dependency to the patched version — the fix "
            "arrives as a reviewable diff instead of a todo."
        )
        if confirm(f"Enable automated security fixes on {ctx.repo}?"):
            ctx.api(f"repos/{ctx.repo}/automated-security-fixes", method="PUT")
            console.print("[green]automated security fixes enabled[/green]")

    path = dependabot_path(ctx.workdir)
    covered = covered_pairs(path) if path else set()
    missing = uncovered(ctx, covered)
    if not missing:
        return

    def write(workdir: Path) -> list[Path]:
        target = dependabot_path(workdir) or workdir / ".github" / "dependabot.yml"
        if target.is_file():
            content = target.read_text().rstrip("\n") + "\n"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = "version: 2\nupdates:\n"
        # Each missing pair carries its own directory, so a nested package gets
        # `directory: "/crates/x-node"`, not a hardcoded "/".
        content += "".join(
            UPDATE_TEMPLATE.format(eco=eid, directory=directory)
            for eid, directory in missing
        )
        target.write_text(content)
        return [target]

    apply_file_fix(
        ctx,
        "dependabot",
        describe=f"add weekly dependabot updates for: {_show(missing)}",
        why="weekly update PRs keep dependencies moving in small, reviewable bumps — "
        "the alternative is one scary mass upgrade a year later",
        write_changes=write,
        commit_message="chore: cover all ecosystems in dependabot.yml",
    )

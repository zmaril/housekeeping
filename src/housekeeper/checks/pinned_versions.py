"""pinned-versions: dependencies pin an exact version, per ecosystem.

A floating specifier (`^1.13.0`, `>=2.0`, `~> 7`, `@v4`) silently drifts: the
same commit resolves to a different dependency tomorrow than today, and nobody
changed a line. That is exactly how fluessig's floating `@typespec/compiler
^1.13.0` shipped a codegen change fleet-wide with no diff to point at. Lockfiles
catch some of this, but not every ecosystem has one in play at resolve time, and
a floating manifest is the thing a human reads and trusts.

We flag FLOATING specifiers per detected ecosystem and leave the pin itself to a
human (dependabot still bumps the pins afterwards). What counts as pinned vs
floating for each ecosystem is not decided here: it lives on the ecosystem
registry as an `Ecosystem.pins` `PinRule` (see `languages.py`), so this check
never hard-codes an exact-semver regex or the `@stable` channel itself. This
module owns only the *manifest-format parsing* — pulling name->specifier pairs
out of each format — because that genuinely differs by format:

- **npm/bun** (`dependencies` + `devDependencies` of every package.json, JSON):
  each value is one specifier the rule classifies. Local (`file:`/`link:`/
  `workspace:`/path) deps are excluded by the rule. peerDependencies are a
  compatibility range by design and only counted in the note.
- **python** (`pyproject.toml` + `requirements.txt`, PEP 508 text): we split off
  the environment marker and extract the name; the rule classifies the remaining
  constraint. A bounded range (`>=1.7,<2.0`) is accepted when `capped_ok`.
- **ruby** (`Gemfile`, `*.gemspec` text): we pull the quoted constraints and
  exclude path/git gems; the rule classifies each constraint (`~>` is bounded,
  accepted when `capped_ok`).
- **actions** (`uses:` in workflows and `.github/actions/**/action.yml`, YAML):
  we split the ref at `@`; the rule classifies the tag (SHA pinned, `@stable`/
  `@oldstable` allowed channels, tags/branches float).
- **cargo** (`Cargo.toml`, TOML): advisory by default because `Cargo.lock` pins
  builds. We read the dep table (string or inline table); the rule classifies the
  version string and recognises a git `rev` SHA as pinned. path and
  `workspace = true` deps are excluded. Reported in the note, not counted, unless
  `[pinned-versions] cargo = "on"`.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

from ..context import RepoContext
from ..languages import ECOSYSTEMS, PinRule
from ..registry import check, failed, passed, skipped
from .ci import workflow_files

# Vendored/generated trees whose manifests aren't the repo's own; hidden dirs
# (leading dot) are skipped on top of these. Actions files under .github/ are
# walked separately, so the hidden-dir skip never hides them.
SKIP_DIRS = {"node_modules", "vendor", "target", "dist", "build", "__pycache__"}

EXAMPLE_CAP = 5  # examples shown per ecosystem before "(+N more)"

# Manifest-format parsers below extract name->specifier pairs; the pinned/floating
# judgement is delegated to each ecosystem's PinRule (in languages.py).
PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")

GEM = re.compile(r"""^\s*gem\s+["']([^"']+)["'](.*)$""")
GEMSPEC = re.compile(
    r"""add(?:_runtime|_development)?_dependency\s*\(?\s*["']([^"']+)["'](.*)$"""
)
QUOTED = re.compile(r"""["']([^"']+)["']""")


def _manifests(workdir: Path, filename: str) -> list[Path]:
    """Every `filename` in the tree, skipping hidden and vendored directories."""
    out = []
    for path in sorted(workdir.rglob(filename)):
        parts = path.relative_to(workdir).parts[:-1]
        if any(p.startswith(".") or p in SKIP_DIRS for p in parts):
            continue
        out.append(path)
    return out


def _load_toml(path: Path) -> dict:
    try:
        data = tomllib.loads(path.read_text(errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _str_list(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _segment(label: str, items: list[tuple[str, str]]) -> str:
    shown = [f"{name} {spec}".strip() for name, spec in items[:EXAMPLE_CAP]]
    extra = len(items) - EXAMPLE_CAP
    suffix = f" (+{extra} more)" if extra > 0 else ""
    return f"{label} {len(items)} ({', '.join(shown)}{suffix})"


# ---- npm / bun ---------------------------------------------------------------


def _scan_npm(
    workdir: Path, ignore: set[str], rule: PinRule
) -> tuple[list[tuple[str, str]], int]:
    floating: list[tuple[str, str]] = []
    peer = 0
    for path in _manifests(workdir, "package.json"):
        try:
            data = json.loads(path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for section in ("dependencies", "devDependencies"):
            deps = data.get(section)
            if not isinstance(deps, dict):
                continue
            for name, spec in deps.items():
                if not isinstance(spec, str) or name in ignore:
                    continue
                category = rule.classify(spec)
                if category == "local":
                    continue  # local / path / workspace dep, not a version
                if category != "pinned":
                    floating.append((name, spec.strip()))
        peers = data.get("peerDependencies")
        if isinstance(peers, dict):
            peer += sum(
                1
                for _, s in peers.items()
                if isinstance(s, str) and rule.classify(s) != "local"
            )
    return floating, peer


# ---- python ------------------------------------------------------------------


def _pep508(req: str) -> tuple[str, str] | None:
    """(name, constraint) for one PEP 508 requirement, or None to skip. The
    constraint is "" when no version is given; direct URL refs (name @ url) skip."""
    req = req.split(";", 1)[0].strip()  # drop environment marker
    if not req or req.startswith("#"):
        return None
    match = PEP508.match(req)
    if not match:
        return None
    name, rest = match.group(1), match.group(2).strip()
    if rest.startswith("@"):
        return None  # direct URL reference (name @ url) — excluded, never flagged
    return name, rest


def _scan_python(
    workdir: Path, ignore: set[str], capped_ok: bool, rule: PinRule
) -> tuple[list[tuple[str, str]], int]:
    reqs: list[str] = []
    for path in _manifests(workdir, "pyproject.toml"):
        data = _load_toml(path)
        project = data.get("project")
        if isinstance(project, dict):
            reqs += _str_list(project.get("dependencies"))
            optional = project.get("optional-dependencies")
            if isinstance(optional, dict):
                for value in optional.values():
                    reqs += _str_list(value)
        groups = data.get("dependency-groups")
        if isinstance(groups, dict):
            for value in groups.values():
                reqs += _str_list(value)
        build = data.get("build-system")
        if isinstance(build, dict):
            reqs += _str_list(build.get("requires"))
    for path in _manifests(workdir, "requirements.txt"):
        try:
            reqs += path.read_text(errors="replace").splitlines()
        except OSError:
            continue

    floating: list[tuple[str, str]] = []
    bounded = 0
    for req in reqs:
        parsed = _pep508(req)
        if parsed is None:
            continue
        name, rest = parsed
        if name in ignore:
            continue
        if not rest:
            floating.append((name, "(no version)"))
            continue
        category = rule.classify(rest)
        if category == "pinned":
            continue
        if category == "bounded":
            bounded += 1
            if not capped_ok:
                floating.append((name, rest))
        else:
            floating.append((name, rest))
    return floating, bounded


# ---- ruby --------------------------------------------------------------------


def _classify_ruby(rest: str, rule: PinRule) -> str:
    """Classify a Gemfile/gemspec dependency's arguments after the name."""
    if re.search(r"\b(path|git|github)\s*:|:\s*(path|git|github)\b", rest):
        return "skip"  # local / vcs gem, not a released version
    constraints = QUOTED.findall(rest)
    if not constraints:
        return "floating"  # no constraint at all
    tilde = False
    for con in constraints:
        category = rule.classify(con)
        if category == "floating":
            return "floating"  # any comparison / unreadable constraint floats
        if category == "bounded":
            tilde = True
    return "bounded" if tilde else "pinned"


def _scan_ruby(
    workdir: Path, ignore: set[str], capped_ok: bool, rule: PinRule
) -> tuple[list[tuple[str, str]], int]:
    floating: list[tuple[str, str]] = []
    bounded = 0
    entries: list[tuple[str, str]] = []
    for path in _manifests(workdir, "Gemfile"):
        for line in path.read_text(errors="replace").splitlines():
            if m := GEM.match(line):
                entries.append((m.group(1), m.group(2)))
    for path in _manifests(workdir, "*.gemspec"):
        for line in path.read_text(errors="replace").splitlines():
            if m := GEMSPEC.search(line):
                entries.append((m.group(1), m.group(2)))
    for name, rest in entries:
        if name in ignore:
            continue
        category = _classify_ruby(rest, rule)
        spec = (QUOTED.findall(rest) or ["(no constraint)"])[0]
        if category == "floating":
            floating.append((name, spec))
        elif category == "bounded":
            bounded += 1
            if not capped_ok:
                floating.append((name, spec))
    return floating, bounded


# ---- cargo -------------------------------------------------------------------


def _classify_cargo(key: str, value: object, rule: PinRule) -> tuple[str, str] | None:
    """(name, spec) when a cargo dep floats, else None (pinned/excluded)."""
    if isinstance(value, str):
        return None if rule.classify(value) == "pinned" else (key, value)
    if not isinstance(value, dict):
        return None
    name = value["package"] if isinstance(value.get("package"), str) else key
    if value.get("workspace") is True or "path" in value:
        return None  # inherited or local — not a version we own here
    if "git" in value:
        rev = value.get("rev")
        if isinstance(rev, str) and rule.sha is not None and rule.sha.fullmatch(rev):
            return None
        for opt in ("rev", "tag", "branch"):
            if isinstance(value.get(opt), str):
                return name, f"git {opt}={value[opt]}"
        return name, "git (default branch)"
    version = value.get("version")
    if isinstance(version, str):
        return None if rule.classify(version) == "pinned" else (name, version)
    return None


def _scan_cargo(
    workdir: Path, ignore: set[str], rule: PinRule
) -> list[tuple[str, str]]:
    floating: list[tuple[str, str]] = []
    for path in _manifests(workdir, "Cargo.toml"):
        data = _load_toml(path)
        tables = [
            data.get(key)
            for key in ("dependencies", "dev-dependencies", "build-dependencies")
        ]
        workspace = data.get("workspace")
        if isinstance(workspace, dict):
            tables.append(workspace.get("dependencies"))
        for table in tables:
            if not isinstance(table, dict):
                continue
            for key, value in table.items():
                result = _classify_cargo(key, value, rule)
                if result and result[0] not in ignore and key not in ignore:
                    floating.append(result)
    return floating


# ---- actions -----------------------------------------------------------------


def _iter_uses(node: object):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _iter_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_uses(item)


def _action_files(workdir: Path) -> list[Path]:
    files = list(workflow_files(workdir))
    actions = workdir / ".github" / "actions"
    if actions.is_dir():
        files += sorted(actions.rglob("action.yml")) + sorted(
            actions.rglob("action.yaml")
        )
    return files


def _scan_actions(
    workdir: Path, ignore: set[str], rule: PinRule
) -> tuple[list[tuple[str, str]], int]:
    floating: list[tuple[str, str]] = []
    channels = 0
    for path in _action_files(workdir):
        try:
            data = yaml.safe_load(path.read_text(errors="replace"))
        except yaml.YAMLError:
            continue
        for uses in _iter_uses(data):
            ref = uses.strip()
            if ref.startswith(("./", "../", "docker://")) or "@" not in ref:
                continue  # local composite or docker image, not a pinnable ref
            name, _, tag = ref.rpartition("@")
            if name in ignore:
                continue
            category = rule.classify(tag)
            if category == "channel":
                channels += 1
            elif category != "pinned":
                floating.append((ref, ""))
    return floating, channels


# ---- the check ---------------------------------------------------------------


@check("pinned-versions", needs=("clone",))
def pinned_versions(ctx: RepoContext):
    settings = ctx.config.section("pinned-versions")
    actions_on = settings.get("actions", True) is not False
    capped_ok = bool(settings.get("capped_ok", False))
    ignore = {str(name) for name in settings.get("ignore", [])}

    languages = {e.language for e in ctx.ecosystems}
    names = {e.name for e in ctx.ecosystems}

    # ctx.ecosystems detects root manifests; extend it with nested ones, since a
    # Rust workspace like entl carries its node/python/ruby crates under
    # crates/*-node, crates/*-python and site/ — root-only detection misses them,
    # but the survey grades them and so must we. The scanners already walk the
    # whole tree; this just decides which ones to run.
    workdir = ctx.workdir
    has_js = "js" in languages or bool(_manifests(workdir, "package.json"))
    has_python = "python" in languages or bool(
        _manifests(workdir, "pyproject.toml") or _manifests(workdir, "requirements.txt")
    )
    has_ruby = "ruby" in languages or bool(
        _manifests(workdir, "Gemfile") or _manifests(workdir, "*.gemspec")
    )
    has_cargo = "cargo" in names or bool(_manifests(workdir, "Cargo.toml"))
    check_actions = actions_on and "github-actions" in names

    if not (has_js or has_python or has_ruby or has_cargo or check_actions):
        return skipped("no dependency manifests or workflows to check")

    # The per-ecosystem pin rules live on the registry; the check reads them off it.
    cargo_rule = _rule("cargo")
    cargo_default = "advisory" if cargo_rule.advisory else "on"
    cargo_mode = str(settings.get("cargo", cargo_default))

    segments: list[str] = []
    checked: list[str] = []
    violations = 0
    bounded_total = 0
    peer_total = 0
    channels_total = 0

    if has_js:
        floating, peer_total = _scan_npm(workdir, ignore, _rule("npm"))
        checked.append("npm/bun")
        violations += len(floating)
        if floating:
            segments.append(_segment("npm/bun", floating))

    if has_python:
        floating, bounded = _scan_python(workdir, ignore, capped_ok, _rule("uv"))
        bounded_total += bounded
        checked.append("python")
        violations += len(floating)
        if floating:
            segments.append(_segment("python", floating))

    if has_ruby:
        floating, bounded = _scan_ruby(workdir, ignore, capped_ok, _rule("ruby"))
        bounded_total += bounded
        checked.append("ruby")
        violations += len(floating)
        if floating:
            segments.append(_segment("ruby", floating))

    cargo_floating: list[tuple[str, str]] = []
    if has_cargo and cargo_mode != "off":
        cargo_floating = _scan_cargo(workdir, ignore, cargo_rule)
        if cargo_mode == "on":
            checked.append("cargo")
            violations += len(cargo_floating)
            if cargo_floating:
                segments.append(_segment("cargo", cargo_floating))

    if check_actions:
        floating, channels_total = _scan_actions(
            workdir, ignore, _rule("github-actions")
        )
        checked.append("actions")
        violations += len(floating)
        if floating:
            segments.append(_segment("actions", floating))

    # Advisory facts, reported whether the check passes or fails.
    advisory: list[str] = []
    if cargo_rule.advisory and cargo_mode != "on" and cargo_floating:
        advisory.append(
            f"cargo: {len(cargo_floating)} floating, advisory only — Cargo.lock "
            'pins builds; set [pinned-versions] cargo = "on" to enforce'
        )
    if bounded_total:
        advisory.append(
            f"{bounded_total} bounded range(s) counted as floating; set capped_ok "
            "= true to accept them"
        )
    if channels_total:
        advisory.append(
            f"{channels_total} action channel(s) allowed (@stable/@oldstable), not flagged"
        )
    if peer_total:
        advisory.append(
            f"{peer_total} peerDependencies not flagged (compatibility ranges)"
        )

    if violations:
        note = (
            "pin to an exact version per ecosystem (dependabot still bumps the "
            "pins); actions pin to a 40-char commit SHA."
        )
        if advisory:
            note += " " + "; ".join(advisory)
        return failed(
            f"{violations} floating version specifier(s): " + "; ".join(segments),
            note,
        )
    return passed(
        f"version specifiers pinned across: {', '.join(checked)}",
        "; ".join(advisory),
    )


def _rule(name: str) -> PinRule:
    """The PinRule for a registry ecosystem (all `js` managers share one rule, as
    do the two python ones), asserted present so callers get a non-optional rule."""
    rule = ECOSYSTEMS[name].pins
    assert rule is not None, f"{name} ecosystem has no pin rule"
    return rule

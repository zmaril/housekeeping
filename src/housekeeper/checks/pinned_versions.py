"""pinned-versions: dependencies pin an exact version, per ecosystem.

A floating specifier (`^1.13.0`, `>=2.0`, `~> 7`, `@v4`) silently drifts: the
same commit resolves to a different dependency tomorrow than today, and nobody
changed a line. That is exactly how fluessig's floating `@typespec/compiler
^1.13.0` shipped a codegen change fleet-wide with no diff to point at. Lockfiles
catch some of this, but not every ecosystem has one in play at resolve time, and
a floating manifest is the thing a human reads and trusts.

We flag FLOATING specifiers per detected ecosystem and leave the pin itself to a
human (dependabot still bumps the pins afterwards):

- **npm/bun** (`dependencies` + `devDependencies` of every package.json): pinned
  is an exact semver (`1.2.3`); `^`/`~`/ranges/dist-tags/git refs float. Local
  (`file:`/`link:`/`workspace:`/path) deps are excluded. peerDependencies are a
  compatibility range by design and only counted in the note.
- **python** (`pyproject.toml` + `requirements.txt`, PEP 508): pinned is a lone
  `==X.Y.Z`; `>=`/`~=`/bare-name/`*` float. A bounded range (`>=1.7,<2.0`) is
  floating by default but counted as "bounded" and accepted when `capped_ok`.
- **ruby** (`Gemfile`, `*.gemspec`): pinned is `= X.Y.Z`; `~>`/`>=`/no-constraint
  float (`~>` is counted bounded, accepted when `capped_ok`). path/git gems excluded.
- **actions** (`uses:` in workflows and `.github/actions/**/action.yml`): pinned
  is a 40-hex commit SHA; tags/branches float. `@stable`/`@oldstable` are bounded
  release channels, allowed (aligned with reproducible-toolchain), not flagged.
- **cargo** (`Cargo.toml`): advisory by default because `Cargo.lock` pins builds.
  Exact `=X.Y.Z` and git `rev = <sha>` are pinned; caret/bare/`*` and git
  branch/tag float. path and `workspace = true` deps excluded. Reported in the
  note, not counted, unless `[pinned-versions] cargo = "on"`.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

from ..context import RepoContext
from ..registry import check, failed, passed, skipped
from .ci import workflow_files

# Vendored/generated trees whose manifests aren't the repo's own; hidden dirs
# (leading dot) are skipped on top of these. Actions files under .github/ are
# walked separately, so the hidden-dir skip never hides them.
SKIP_DIRS = {"node_modules", "vendor", "target", "dist", "build", "__pycache__"}

EXAMPLE_CAP = 5  # examples shown per ecosystem before "(+N more)"

# npm exact semver: 1.2.3, 1.0.0-beta.5. Anything with ^ ~ range wildcard floats.
NPM_EXACT = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")
NPM_LOCAL = ("file:", "link:", "workspace:", "portal:", ".", "/")

SHA40 = re.compile(r"[0-9a-f]{40}")
# Bounded moving release channels an action ref may target — allowed, not floating.
ACTION_CHANNELS = {"stable", "oldstable"}

PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
PEP508_CLAUSE = re.compile(r"^(===|==|>=|<=|!=|~=|>|<)\s*(.+)$")

GEM = re.compile(r"""^\s*gem\s+["']([^"']+)["'](.*)$""")
GEMSPEC = re.compile(
    r"""add(?:_runtime|_development)?_dependency\s*\(?\s*["']([^"']+)["'](.*)$"""
)


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


def _scan_npm(workdir: Path, ignore: set[str]) -> tuple[list[tuple[str, str]], int]:
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
                spec = spec.strip()
                if spec.startswith(NPM_LOCAL):
                    continue  # local / path / workspace dep, not a version
                if not NPM_EXACT.fullmatch(spec):
                    floating.append((name, spec))
        peers = data.get("peerDependencies")
        if isinstance(peers, dict):
            peer += sum(
                1
                for _, s in peers.items()
                if isinstance(s, str) and not s.strip().startswith(NPM_LOCAL)
            )
    return floating, peer


# ---- python ------------------------------------------------------------------


def _classify_python(req: str) -> tuple[str, str, str] | None:
    """(category, name, spec) for one PEP 508 requirement, or None to skip."""
    req = req.split(";", 1)[0].strip()  # drop environment marker
    if not req or req.startswith("#"):
        return None
    match = PEP508.match(req)
    if not match:
        return None
    name, rest = match.group(1), match.group(2).strip()
    if rest.startswith("@"):
        return None  # direct URL reference (name @ url) — excluded, never flagged
    if not rest:
        return "floating", name, "(no version)"
    clauses = [c.strip() for c in rest.split(",") if c.strip()]
    parsed = [
        (m.group(1), m.group(2).strip())
        for c in clauses
        if (m := PEP508_CLAUSE.match(c))
    ]
    if len(parsed) != len(clauses):
        return "floating", name, rest  # unparseable clause (e.g. bare *)
    if len(parsed) == 1 and parsed[0][0] in ("==", "===") and "*" not in parsed[0][1]:
        return "pinned", name, rest
    has_lower = any(op in (">", ">=") for op, _ in parsed)
    has_upper = any(op in ("<", "<=") for op, _ in parsed)
    if has_lower and has_upper:
        return "bounded", name, rest
    return "floating", name, rest


def _scan_python(
    workdir: Path, ignore: set[str], capped_ok: bool
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
        result = _classify_python(req)
        if result is None:
            continue
        category, name, spec = result
        if name in ignore:
            continue
        if category == "floating":
            floating.append((name, spec))
        elif category == "bounded":
            bounded += 1
            if not capped_ok:
                floating.append((name, spec))
    return floating, bounded


# ---- ruby --------------------------------------------------------------------


def _classify_ruby(rest: str) -> str:
    """Classify a Gemfile/gemspec dependency's arguments after the name."""
    if re.search(r"\b(path|git|github)\s*:|:\s*(path|git|github)\b", rest):
        return "skip"  # local / vcs gem, not a released version
    constraints = re.findall(r"""["']([^"']+)["']""", rest)
    if not constraints:
        return "floating"  # no constraint at all
    tilde = False
    for con in constraints:
        con = con.strip()
        if con.startswith("~>"):
            tilde = True
        elif re.match(r"(>=|<=|>|<|!=)", con):
            return "floating"
        elif not re.fullmatch(r"=?\s*v?\d+(?:\.\d+)*", con):
            return "floating"  # anything we can't read as an exact pin
    return "bounded" if tilde else "pinned"


def _scan_ruby(
    workdir: Path, ignore: set[str], capped_ok: bool
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
        category = _classify_ruby(rest)
        spec = (re.findall(r"""["']([^"']+)["']""", rest) or ["(no constraint)"])[0]
        if category == "floating":
            floating.append((name, spec))
        elif category == "bounded":
            bounded += 1
            if not capped_ok:
                floating.append((name, spec))
    return floating, bounded


# ---- cargo -------------------------------------------------------------------


def _classify_cargo(key: str, value: object) -> tuple[str, str] | None:
    """(name, spec) when a cargo dep floats, else None (pinned/excluded)."""
    if isinstance(value, str):
        return None if value.strip().startswith("=") else (key, value)
    if not isinstance(value, dict):
        return None
    name = value["package"] if isinstance(value.get("package"), str) else key
    if value.get("workspace") is True or "path" in value:
        return None  # inherited or local — not a version we own here
    if "git" in value:
        rev = value.get("rev")
        if isinstance(rev, str) and SHA40.fullmatch(rev):
            return None
        for opt in ("rev", "tag", "branch"):
            if isinstance(value.get(opt), str):
                return name, f"git {opt}={value[opt]}"
        return name, "git (default branch)"
    version = value.get("version")
    if isinstance(version, str):
        return None if version.strip().startswith("=") else (name, version)
    return None


def _scan_cargo(workdir: Path, ignore: set[str]) -> list[tuple[str, str]]:
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
                result = _classify_cargo(key, value)
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


def _scan_actions(workdir: Path, ignore: set[str]) -> tuple[list[tuple[str, str]], int]:
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
            if tag in ACTION_CHANNELS:
                channels += 1
            elif not SHA40.fullmatch(tag):
                floating.append((ref, ""))
    return floating, channels


# ---- the check ---------------------------------------------------------------


@check("pinned-versions", needs=("clone",))
def pinned_versions(ctx: RepoContext):
    settings = ctx.config.section("pinned-versions")
    cargo_mode = str(settings.get("cargo", "advisory"))
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

    segments: list[str] = []
    checked: list[str] = []
    violations = 0
    bounded_total = 0
    peer_total = 0
    channels_total = 0

    if has_js:
        floating, peer_total = _scan_npm(ctx.workdir, ignore)
        checked.append("npm/bun")
        violations += len(floating)
        if floating:
            segments.append(_segment("npm/bun", floating))

    if has_python:
        floating, bounded = _scan_python(ctx.workdir, ignore, capped_ok)
        bounded_total += bounded
        checked.append("python")
        violations += len(floating)
        if floating:
            segments.append(_segment("python", floating))

    if has_ruby:
        floating, bounded = _scan_ruby(ctx.workdir, ignore, capped_ok)
        bounded_total += bounded
        checked.append("ruby")
        violations += len(floating)
        if floating:
            segments.append(_segment("ruby", floating))

    cargo_floating: list[tuple[str, str]] = []
    if has_cargo and cargo_mode != "off":
        cargo_floating = _scan_cargo(ctx.workdir, ignore)
        if cargo_mode == "on":
            checked.append("cargo")
            violations += len(cargo_floating)
            if cargo_floating:
                segments.append(_segment("cargo", cargo_floating))

    if check_actions:
        floating, channels_total = _scan_actions(ctx.workdir, ignore)
        checked.append("actions")
        violations += len(floating)
        if floating:
            segments.append(_segment("actions", floating))

    # Advisory facts, reported whether the check passes or fails.
    advisory: list[str] = []
    if cargo_mode != "on" and cargo_floating:
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

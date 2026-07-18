"""coverage: each detected language ecosystem has a coverage tool configured.

Presence-only — it verifies that *some* coverage tool is wired up somewhere
(a config file, a CI step, a task-runner target, or a manifest dependency), not a
coverage percentage or threshold. Each repo configures the specifics as makes
sense; the fleet only asks that a coverage tool exist per language. Advisory by
default (severity=recommended), following the ci-green advisory-first precedent."""

from __future__ import annotations

import re
from pathlib import Path

from ..context import RepoContext
from ..registry import Result, check, failed, passed, skipped

# Ecosystem languages this check knows how to look for coverage tooling in. An
# ecosystem whose language isn't here (ruby, go, github-actions) doesn't
# participate — presence is only asserted for languages we have signals for.
COVERAGE_LANGUAGES = ("rust", "js", "python")

# The tool named in the failure message per language — actionable, not vague.
RECOMMENDED = {
    "rust": "add a `cargo llvm-cov` CI step or a Makefile/justfile target",
    "js": "add `bun test --coverage` (or c8/nyc/vitest --coverage) in CI or a package.json script",
    "python": "add pytest-cov (a `--cov` addopt or `[tool.coverage]` in pyproject)",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _ci_and_runner_text(workdir: Path) -> str:
    """Lower-cased concatenation of everywhere a coverage tool tends to be wired:
    CI workflows, the Makefile/justfile, and scripts/."""
    parts: list[str] = []
    workflows = workdir / ".github" / "workflows"
    if workflows.is_dir():
        for p in sorted(workflows.glob("*.y*ml")):
            parts.append(_read(p))
    for name in ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"):
        p = workdir / name
        if p.is_file():
            parts.append(_read(p))
    scripts = workdir / "scripts"
    if scripts.is_dir():
        for p in sorted(scripts.rglob("*")):
            if p.is_file():
                parts.append(_read(p))
    return "\n".join(parts).lower()


def _generic_signal(workdir: Path, ci_runner: str) -> str | None:
    """Coverage signals that count for any ecosystem: a codecov/coverage config
    file at the root, or codecov/coveralls referenced in CI."""
    for name in ("codecov.yml", ".codecov.yml", ".coveragerc", ".coverage"):
        if (workdir / name).is_file():
            return name
    if "codecov" in ci_runner:
        return "codecov in CI"
    if "coveralls" in ci_runner:
        return "coveralls in CI"
    return None


def _rust_signal(workdir: Path, ci_runner: str) -> str | None:
    for tok in ("cargo-llvm-cov", "llvm-cov", "tarpaulin", "grcov"):
        if tok in ci_runner:
            return tok
    return None


def _js_signal(workdir: Path, ci_runner: str) -> str | None:
    bunfig = workdir / "bunfig.toml"
    if bunfig.is_file() and "coverage" in _read(bunfig).lower():
        return "bunfig.toml coverage"
    haystack = ci_runner + "\n" + _read(workdir / "package.json").lower()
    for cfg in ("vitest.config", "jest.config", "vite.config"):
        for p in sorted(workdir.glob(f"{cfg}.*")):
            haystack += "\n" + _read(p).lower()
    for tok in ("--coverage", "coveragethreshold"):
        if tok in haystack:
            return tok
    for tok in ("c8", "nyc"):
        if re.search(rf"\b{tok}\b", haystack):
            return tok
    return None


def _python_signal(workdir: Path, ci_runner: str) -> str | None:
    if (workdir / ".coveragerc").is_file():
        return ".coveragerc"
    pyproject = _read(workdir / "pyproject.toml").lower()
    if any(s in pyproject for s in ("pytest-cov", "[tool.coverage", "--cov")):
        return "pytest-cov / [tool.coverage] in pyproject.toml"
    if '"coverage' in pyproject or "'coverage" in pyproject:
        return "coverage dependency in pyproject.toml"
    for name in ("pytest.ini", "tox.ini", "setup.cfg"):
        text = _read(workdir / name).lower()
        if any(
            s in text
            for s in ("--cov", "pytest-cov", "[tool.coverage", "[coverage:run]")
        ):
            return f"coverage config in {name}"
    reqs = list(workdir.glob("requirements*.txt")) + list(
        (workdir / "requirements").glob("*.txt")
    )
    for req in sorted(reqs):
        text = _read(req).lower()
        if "pytest-cov" in text or re.search(r"(?m)^\s*coverage\b", text):
            return f"coverage dep in {req.name}"
    return None


_LANG_SIGNAL = {
    "rust": _rust_signal,
    "js": _js_signal,
    "python": _python_signal,
}


@check("coverage", needs=("clone",))
def coverage(ctx: RepoContext) -> Result:
    """Every detected language ecosystem has a coverage tool configured somewhere."""
    workdir = ctx.workdir
    languages = sorted(
        {eco.language for eco in ctx.ecosystems if eco.language in COVERAGE_LANGUAGES}
    )
    if not languages:
        return skipped("no rust/js/python ecosystem detected — nothing to check")

    ci_runner = _ci_and_runner_text(workdir)
    generic = _generic_signal(workdir, ci_runner)

    found: list[str] = []
    missing: list[str] = []
    for lang in languages:
        signal = _LANG_SIGNAL[lang](workdir, ci_runner) or generic
        if signal is not None:
            found.append(f"{lang}: {signal}")
        else:
            missing.append(f"{lang}: no coverage tool detected — {RECOMMENDED[lang]}")

    if missing:
        note = ("found — " + "; ".join(found)) if found else ""
        return failed("; ".join(missing), note=note)
    return passed("coverage tool present — " + "; ".join(found))

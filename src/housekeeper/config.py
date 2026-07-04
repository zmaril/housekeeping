"""Severity defaults and per-repo .housekeeping.toml overrides."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

SEVERITIES = ("required", "recommended", "off")

DEFAULT_SEVERITY = {
    "branch-protection": "required",
    "required-checks": "required",
    "ci-exists": "required",
    "ci-scoped": "recommended",
    "ci-green": "required",
    "typecheck": "required",
    "builds": "required",
    "codegen-drift": "required",
    "dependabot": "required",
    "secret-scanning": "required",
    "workflow-permissions": "required",
    "lockfiles": "required",
    "gitignore": "recommended",
    "stray-files": "recommended",
    "conventional-commits": "recommended",
    "straitjacket": "required",
    "readme": "required",
    "action-badge": "recommended",
    "website": "required",
    "license": "required",
    "changelog": "required",
    "repo-meta": "recommended",
    "stale": "recommended",
}

# The defaults above encode what good code looks like, public or private.
# Private repos have no audience, so audience-facing checks soften.
PRIVATE_SEVERITY = {
    "website": "recommended",
    "license": "recommended",
    "changelog": "recommended",
    "readme": "recommended",
    "repo-meta": "off",
}


class Config:
    def __init__(self, repo_overrides: dict[str, Any] | None = None):
        self._repo = repo_overrides or {}

    @classmethod
    def load(cls, workdir: Path | None) -> "Config":
        if workdir:
            path = workdir / ".housekeeping.toml"
            if path.is_file():
                return cls(tomllib.loads(path.read_text()))
        return cls()

    def severity(self, check_name: str, visibility: str) -> str:
        override = self._repo.get("checks", {}).get(check_name)
        if override is not None:
            if override not in SEVERITIES:
                raise ValueError(
                    f".housekeeping.toml: checks.{check_name} = {override!r}, "
                    f"expected one of {SEVERITIES}"
                )
            return override
        if visibility == "private" and check_name in PRIVATE_SEVERITY:
            return PRIVATE_SEVERITY[check_name]
        return DEFAULT_SEVERITY.get(check_name, "required")

    def section(self, name: str) -> dict[str, Any]:
        """Per-check settings, e.g. [website] url = "..."."""
        value = self._repo.get(name, {})
        return value if isinstance(value, dict) else {}

    def unknown_keys(self, known_checks: set[str]) -> list[str]:
        """Config keys that nothing reads — a typo, or config from a newer
        housekeeping. Surfaced, never silently ignored."""
        problems = []
        for section in self._repo:
            if (
                section not in ("checks", "fleet", "codegen", "logo")
                and section not in known_checks
            ):
                problems.append(f"[{section}]")
        for check_name in self._repo.get("checks", {}):
            if check_name not in known_checks:
                problems.append(f"checks.{check_name}")
        return sorted(problems)

    @property
    def codegen(self) -> list[dict[str, Any]]:
        """Declared [[codegen]] regen commands, for the codegen-drift check."""
        value = self._repo.get("codegen", [])
        return (
            [entry for entry in value if isinstance(entry, dict)]
            if isinstance(value, list)
            else []
        )

    @property
    def fleet(self) -> str:
        """The captain repo this member belongs to, if declared."""
        value = self._repo.get("fleet", "")
        return value if isinstance(value, str) else ""

    @property
    def logo(self) -> str:
        """Optional repo logo for the fleet dashboard — an image URL, or a repo-relative
        path (resolved to its raw URL when rendered)."""
        value = self._repo.get("logo", "")
        return value if isinstance(value, str) else ""

    @property
    def raw(self) -> dict[str, Any]:
        return self._repo

    def apply_locked(self, locked: list[str], policy_checks: dict[str, str]) -> None:
        """Locked keys are fleet law: local values are discarded, and locked
        check severities come from fleet policy (or defaults)."""
        for key in locked:
            section, _, leaf = key.partition(".")
            if section == "checks":
                if leaf in policy_checks:
                    self._repo.setdefault("checks", {})[leaf] = policy_checks[leaf]
                else:
                    self._repo.get("checks", {}).pop(leaf, None)
            else:
                table = self._repo.get(section)
                if isinstance(table, dict):
                    table.pop(leaf, None)

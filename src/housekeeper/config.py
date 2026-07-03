"""Severity defaults and per-repo .housekeeping.toml overrides."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

SEVERITIES = ("required", "recommended", "off")

DEFAULT_SEVERITY = {
    "branch-protection": "required",
    "ci-exists": "required",
    "ci-green": "required",
    "dependabot": "required",
    "lockfiles": "required",
    "straitjacket": "required",
    "readme": "required",
    "website": "required",
    "license": "required",
    "repo-meta": "recommended",
    "stale": "recommended",
}

# Private repos get a softer profile.
PRIVATE_SEVERITY = {
    "website": "recommended",
    "license": "recommended",
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

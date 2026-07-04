"""Import order here is display order in the report."""

from . import (  # noqa: F401
    branch_protection,
    ci,
    typecheck,
    dependabot,
    secret_scanning,
    workflow_permissions,
    lockfiles,
    gitignore,
    stray_files,
    conventional_commits,
    straitjacket,
    readme,
    action_badge,
    website,
    license,
    changelog,
    repo_meta,
    stale,
)

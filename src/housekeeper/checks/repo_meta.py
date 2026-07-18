"""Repo description + topics are declared in the README and reconciled with GitHub.

The README is the source of truth. Invisible HTML-comment markers declare the repo's
one-line description (its tagline) and its topics (its tags), and the check asserts
GitHub's actual values match what the README declares:

    <!-- housekeeper:description One-line tagline goes here. -->
    <!-- housekeeper:topics rust, cli, codegen -->

`housekeeper fix repo-meta` pushes the README-declared values to GitHub (needs an admin
token). When a repo has no markers yet, the fix instead seeds them into the README from
GitHub's current description/topics, so adopting the convention is a one-liner.
"""

from __future__ import annotations

import re

from ..context import GhError, RepoContext
from ..fixing import apply_file_fix, confirm, console
from ..registry import check, failed, fix_for, passed
from .readme import find_readme

# Bare directive markers, one per line, mirroring fluessig's `<!-- fl:... -->` idiom.
MARKER = re.compile(r"^<!--\s*housekeeper:(\w+)\s+(.*?)\s*-->\s*$", re.M)

# GitHub topic rules: lowercase letters/numbers/hyphens, starting alnum; <=50 chars each,
# <=20 topics per repo. (Hyphens only - dots and underscores are rejected by the UI.)
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_TOPIC_LEN = 50
MAX_TOPICS = 20


def read_markers(readme_text: str) -> dict:
    """Parse the housekeeper metadata markers out of a README.

    Returns a dict that may hold "description" (the trimmed text) and/or "topics" (a
    normalized list: comma-split, stripped, lowercased, empties dropped). A key is
    absent when its marker is not present in the README.
    """
    markers: dict = {}
    for directive, value in MARKER.findall(readme_text):
        if directive == "description":
            markers["description"] = value.strip()
        elif directive == "topics":
            markers["topics"] = [
                t.strip().lower() for t in value.split(",") if t.strip()
            ]
    return markers


def _topic_problems(topics: list[str]) -> list[str]:
    problems = []
    invalid = [t for t in topics if not TOPIC.match(t) or len(t) > MAX_TOPIC_LEN]
    if invalid:
        problems.append(
            "invalid topics (lowercase letters/numbers/hyphens, start alnum, "
            f"<= {MAX_TOPIC_LEN} chars): {', '.join(invalid)}"
        )
    if len(topics) > MAX_TOPICS:
        problems.append(f"too many topics ({len(topics)} > {MAX_TOPICS})")
    return problems


@check("repo-meta", needs=("clone", "api"))
def repo_meta(ctx: RepoContext):
    info = ctx.repo_info
    path = find_readme(ctx.workdir)
    markers = read_markers(path.read_text(errors="replace")) if path else {}
    problems = []
    n_topics = 0

    if "description" in markers:
        declared = markers["description"].strip()
        actual = (info.get("description") or "").strip()
        if declared != actual:
            problems.append(
                f"description out of sync: README declares {declared!r}, "
                f"GitHub has {actual!r}"
            )
    else:
        problems.append(
            "no <!-- housekeeper:description ... --> marker in README "
            "(add it so the tagline stays in sync)"
        )

    if "topics" in markers:
        declared_topics = markers["topics"]
        n_topics = len(declared_topics)
        problems += _topic_problems(declared_topics)
        actual_topics = sorted(info.get("topics") or [])
        if sorted(declared_topics) != actual_topics:
            problems.append(
                f"topics out of sync: README declares {sorted(declared_topics)}, "
                f"GitHub has {actual_topics}"
            )
    else:
        problems.append("no <!-- housekeeper:topics ... --> marker in README")

    if not info.get("has_issues"):
        problems.append("issues disabled")

    if problems:
        return failed("; ".join(problems))
    return passed(
        f"description + {n_topics} topics in sync with README; issues enabled"
    )


def _seed_markers(ctx: RepoContext, info: dict) -> None:
    """Bootstrap: write the two markers at the top of the README from GitHub's values."""
    description = (info.get("description") or "").strip()
    topics = sorted(info.get("topics") or [])
    header = (
        f"<!-- housekeeper:description {description} -->\n"
        f"<!-- housekeeper:topics {', '.join(topics)} -->\n"
    )

    def write_changes(workdir):
        path = find_readme(workdir)
        if path is None:
            console.print("[red]no README to seed markers into[/red]")
            return []
        path.write_text(header + path.read_text(errors="replace"))
        return [path]

    apply_file_fix(
        ctx,
        "repo-meta",
        describe="add housekeeper description/topics markers at the top of the README",
        why=(
            "seed housekeeper metadata markers into the README from the repo's current "
            "description/topics, so the README becomes the source of truth and future "
            "edits to the markers drive GitHub."
        ),
        write_changes=write_changes,
        commit_message="docs: declare repo description + topics via housekeeper markers",
    )


def _write(ctx: RepoContext, path: str, method: str, payload: dict) -> bool:
    """Do a repo write; on 403 print the admin-token hint and signal stop (False)."""
    try:
        ctx.api(path, method=method, input=payload)
    except GhError as e:
        if e.status == 403:
            console.print(
                "[red]token lacks admin (HTTP 403)[/red] - re-run with an admin token, "
                "or set it by hand in Settings."
            )
            return False
        raise
    return True


@fix_for("repo-meta")
def fix(ctx: RepoContext):
    info = ctx.repo_info
    path = find_readme(ctx.workdir)
    markers = read_markers(path.read_text(errors="replace")) if path else {}

    if not markers:
        # No markers yet: seed them into the README from GitHub's current values.
        _seed_markers(ctx, info)
    else:
        # Markers present: the README is the source of truth - push it to GitHub.
        declared = markers.get("description")
        if declared is not None:
            declared = declared.strip()
            actual = (info.get("description") or "").strip()
            if declared != actual:
                console.print(
                    f"\nThis will set {ctx.repo}'s description to [cyan]{declared!r}[/cyan] "
                    "to match the README."
                )
                if confirm(f"Set description to {declared!r}?"):
                    if not _write(
                        ctx, f"repos/{ctx.repo}", "PATCH", {"description": declared}
                    ):
                        return
                    console.print("[green]description set[/green]")

        topics = markers.get("topics")
        if topics is not None:
            topic_problems = _topic_problems(topics)
            if topic_problems:
                console.print(
                    f"[red]{'; '.join(topic_problems)}[/red] - fix the README markers first"
                )
            else:
                actual_topics = sorted(info.get("topics") or [])
                if sorted(topics) != actual_topics:
                    console.print(
                        f"\nThis will set {ctx.repo}'s topics to [cyan]{sorted(topics)}[/cyan] "
                        "to match the README."
                    )
                    if confirm(f"Set topics to {sorted(topics)}?"):
                        if not _write(
                            ctx, f"repos/{ctx.repo}/topics", "PUT", {"names": topics}
                        ):
                            return
                        console.print("[green]topics set[/green]")

    if not info.get("has_issues"):
        console.print(
            "\n[dim]Why: issues give users somewhere to report bugs and ask questions - "
            "with them off, feedback lands on social media or nowhere.[/dim]"
        )
        if confirm("Enable issues?"):
            ctx.api(f"repos/{ctx.repo}", method="PATCH", input={"has_issues": True})
            console.print("[green]issues enabled[/green]")

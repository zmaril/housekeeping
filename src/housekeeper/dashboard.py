"""Render a fleet audit into a self-contained HTML dashboard: a matrix of every check
(row) against every member (column, with its optional logo), each cell the status.

Fed the same per-repo payloads `housekeeper check` produces, so the dashboard is just a
view — no second source of truth."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .registry import CHECKS

# glyph + css class per outcome; a recommended failure is a warn, not a fail.
CELL = {
    "pass": ("✓", "ok"),
    "warn": ("!", "warn"),
    "fail": ("✗", "bad"),
    "error": ("!", "bad"),
    "skip": ("–", "skip"),
    "off": ("·", "off"),
    "none": ("", "off"),
}

LEGEND = [
    ("ok", "✓ pass"),
    ("warn", "! warn"),
    ("bad", "✗ fail"),
    ("skip", "– skip"),
    ("off", "· off / n-a"),
]

# metadata rows (version text, not a status glyph): which shared-CI ref each repo pins.
CI_ROWS = [("housekeeping", "housekeeping CI"), ("straitjacket", "straitjacket CI")]


def logo_url(repo: str, logo: str) -> str:
    """An image URL for the repo: a full URL as-is, else a repo-relative path resolved
    to its raw.githubusercontent URL."""
    if not logo:
        return ""
    if logo.startswith(("http://", "https://", "data:")):
        return logo
    return f"https://raw.githubusercontent.com/{repo}/HEAD/{logo.lstrip('/')}"


def _outcome(row: dict) -> str:
    status = row["status"]
    if status == "fail" and row.get("severity") == "recommended":
        return "warn"
    return status


def _rows(payloads: list[dict]) -> list[str]:
    """Every check that appears, in registry (display) order; unknowns (e.g. `config`) last."""
    seen: set[str] = set()
    for payload in payloads:
        for row in payload["results"]:
            seen.add(row["check"])
    order = list(CHECKS.keys())
    known = [c for c in order if c in seen]
    extra = sorted(c for c in seen if c not in CHECKS)
    return known + extra


def _repo_header(member, payload: dict | None) -> str:
    repo = member.repo
    short = html.escape(repo.split("/")[-1])
    href = f"https://github.com/{html.escape(repo)}"
    if payload is None:
        return (
            f'<th class="repo bad" title="unreachable">'
            f'<a href="{href}"><span>{short}</span></a></th>'
        )
    logo = logo_url(repo, payload.get("logo", ""))
    img = f'<img src="{html.escape(logo)}" alt="" loading="lazy">' if logo else ""
    return f'<th class="repo"><a href="{href}">{img}<span>{short}</span></a></th>'


def render_matrix(
    name: str, members: list, payloads: list[dict | None], now: str | None = None
) -> str:
    now = now or datetime.now(timezone.utc).isoformat(timespec="minutes")
    live = [p for p in payloads if p]
    checks = _rows(live)

    repo_cells = [_repo_header(m, p) for m, p in zip(members, payloads)]
    head = '<th class="corner"></th>' + "".join(repo_cells)
    foot = '<th class="corner"></th>' + "".join(repo_cells)

    # version metadata rows: which shared-CI ref each repo pins.
    meta_rows = []
    for i, (key, label) in enumerate(CI_ROWS):
        cells = []
        for payload in payloads:
            ver = (
                "–"
                if payload is None
                else (payload.get("ci_versions", {}).get(key) or "–")
            )
            cells.append(
                f'<td class="ver" title="{html.escape(label)}: {html.escape(ver)}">{html.escape(ver)}</td>'
            )
        cls = "meta last" if i == len(CI_ROWS) - 1 else "meta"
        meta_rows.append(
            f'<tr class="{cls}"><th class="check">{html.escape(label)}</th>{"".join(cells)}</tr>'
        )

    # one lookup per column (member); None marks an unreachable repo.
    columns = [{r["check"]: r for r in p["results"]} if p else None for p in payloads]

    body_rows = []
    for check in checks:
        cells = []
        for by_check in columns:
            if by_check is None:
                cells.append('<td class="off" title="unreachable">·</td>')
                continue
            row = by_check.get(check)
            outcome = _outcome(row) if row else "none"
            glyph, cls = CELL.get(outcome, CELL["none"])
            title = (
                html.escape(f"{check}: {row['details']}")
                if row
                else f"{check}: not run"
            )
            cells.append(f'<td class="{cls}" title="{title}">{glyph}</td>')
        body_rows.append(
            f'<tr><th class="check">{html.escape(check)}</th>{"".join(cells)}</tr>'
        )

    legend = " ".join(
        f'<span class="tag {cls}">{html.escape(label)}</span>' for cls, label in LEGEND
    )
    return _PAGE.format(
        name=html.escape(name),
        now=html.escape(now),
        legend=legend,
        head=head,
        meta="\n".join(meta_rows),
        body="\n".join(body_rows),
        foot=foot,
    )


def render_document(
    name: str, members: list, payloads: list[dict | None], now: str | None = None
) -> str:
    """A full, standalone HTML document (for a file / GitHub Pages) wrapping the matrix."""
    body = render_matrix(name, members, payloads, now)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(name)} fleet</title>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


_PAGE = """\
<h1>{name} <span class="sub">fleet check matrix · {now}</span></h1>
<div class="legend">{legend}</div>
<div class="scroll">
<table>
<thead><tr>{head}</tr></thead>
<tbody>
{meta}
{body}
</tbody>
<tfoot><tr>{foot}</tr></tfoot>
</table>
</div>
<style>
:root {{ --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e; --skip:#8c959f; --line:#d0d7de; --bg:#fff; --fg:#1f2328; --head:#f6f8fa; }}
@media (prefers-color-scheme: dark) {{ :root {{ --ok:#3fb950; --warn:#d29922; --bad:#f85149; --skip:#6e7681; --line:#30363d; --bg:#0d1117; --fg:#e6edf3; --head:#161b22; }} }}
:root[data-theme="dark"] {{ --ok:#3fb950; --warn:#d29922; --bad:#f85149; --skip:#6e7681; --line:#30363d; --bg:#0d1117; --fg:#e6edf3; --head:#161b22; }}
:root[data-theme="light"] {{ --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e; --skip:#8c959f; --line:#d0d7de; --bg:#fff; --fg:#1f2328; --head:#f6f8fa; }}
body {{ font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--fg); background: var(--bg); margin: 2rem; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
h1 .sub {{ font-size: .8rem; color: var(--skip); font-weight: 400; }}
.legend {{ margin: .5rem 0 1rem; }}
.tag {{ display: inline-block; margin-right: .75rem; font-size: .8rem; }}
.tag.ok {{ color: var(--ok); }} .tag.warn {{ color: var(--warn); }} .tag.bad {{ color: var(--bad); }} .tag.skip {{ color: var(--skip); }} .tag.off {{ color: var(--skip); }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid var(--line); }}
td {{ width: 2rem; height: 2rem; text-align: center; font-weight: 700; }}
td.ok {{ color: var(--ok); }} td.warn {{ color: var(--warn); background: color-mix(in srgb, var(--warn) 12%, transparent); }}
td.bad {{ color: var(--bad); background: color-mix(in srgb, var(--bad) 12%, transparent); }}
td.skip, td.off {{ color: var(--skip); }}
th.repo {{ background: var(--head); height: 7rem; padding: .5rem .3rem; }}
thead th.repo {{ vertical-align: bottom; }}
tfoot th.repo {{ vertical-align: top; }}
th.repo a {{ display: flex; flex-direction: column; align-items: center; gap: .4rem; color: inherit; text-decoration: none; }}
th.repo img {{ width: 22px; height: 22px; border-radius: 4px; object-fit: contain; }}
th.repo span {{ writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; font-weight: 500; }}
th.repo.bad span {{ color: var(--bad); }}
th.corner {{ background: var(--head); position: sticky; left: 0; z-index: 1; }}
th.check {{ background: var(--head); text-align: left; padding: .3rem .8rem; position: sticky; left: 0; white-space: nowrap; font-weight: 500; }}
tr.meta td.ver {{ background: var(--head); font: 600 11px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--fg); white-space: nowrap; text-align: center; padding: 0 .45rem; }}
tr.meta th.check {{ font-style: italic; font-weight: 500; }}
tr.last td, tr.last th {{ border-bottom: 2px solid var(--skip); }}
</style>
"""

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

# label + hover tooltip per legend entry; the tooltip spells out what the glyph means.
LEGEND = [
    ("ok", "✓ pass", "check met"),
    (
        "warn",
        "! warn — recommended, not required",
        "a recommended check isn't met; advisory, doesn't fail the fleet",
    ),
    ("bad", "✗ fail — required", "a required check isn't met; fails the fleet"),
    ("skip", "– skip", "not applicable to this repo"),
    ("off", "· off / n-a", "disabled for this repo, or the check didn't run"),
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


# the second table's kinds: (label, badge css, payload activity key). PRs first.
ACTIVITY_KINDS = [("PR", "pr", "pulls"), ("issue", "issue", "issues")]


def _activity_table(members: list, payloads: list[dict | None]) -> str:
    """A second, standalone table: every open PR then every open issue across the
    fleet, one row each, with the repo as a column. Scrolls within its own box."""
    rows = []
    totals = {"pulls": 0, "issues": 0}
    for label, badge, key in ACTIVITY_KINDS:
        for member, payload in zip(members, payloads):
            if payload is None:
                continue
            repo = member.repo
            short = html.escape(repo.split("/")[-1])
            repo_href = f"https://github.com/{html.escape(repo)}"
            for it in (payload.get("activity") or {}).get(key, []):
                totals[key] += 1
                url = html.escape(it["url"])
                rows.append(
                    "<tr>"
                    f'<td class="a-repo"><a href="{repo_href}">{short}</a></td>'
                    f'<td><span class="kind {badge}">{label}</span></td>'
                    f'<td class="a-num"><a href="{url}">#{it["number"]}</a></td>'
                    f'<td class="a-title"><a href="{url}">{html.escape(it["title"])}</a></td>'
                    "</tr>"
                )
    body = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="4" class="empty">nothing open across the fleet</td></tr>'
    )
    return (
        '<section class="activity">'
        '<h2 class="section-title">Open pull requests &amp; issues '
        f'<span class="sub">{totals["pulls"]} PRs · {totals["issues"]} issues</span>'
        "</h2>"
        '<div class="activity-scroll"><table class="activity-table">'
        "<thead><tr><th>repo</th><th>kind</th><th>#</th><th>title</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
        "</section>"
    )


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
        f'<span class="tag {cls}" title="{html.escape(tip)}">{html.escape(label)}</span>'
        for cls, label, tip in LEGEND
    )
    return _PAGE.format(
        name=html.escape(name),
        now=html.escape(now),
        legend=legend,
        head=head,
        meta="\n".join(meta_rows),
        body="\n".join(body_rows),
        foot=foot,
        activity=_activity_table(members, payloads),
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
{activity}
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
/* second table: every open PR then issue across the fleet, repo as a column */
.activity {{ margin-top: 2.5rem; }}
.section-title {{ font-size: 1.1rem; margin: 0 0 .75rem; }}
.section-title .sub {{ font-size: .8rem; color: var(--skip); font-weight: 400; }}
.activity-scroll {{ max-height: 34rem; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }}
table.activity-table {{ border-collapse: collapse; width: 100%; }}
.activity-table th, .activity-table td {{ border: 0; border-bottom: 1px solid var(--line); width: auto; height: auto; text-align: left; font-weight: 400; padding: .4rem .7rem; vertical-align: baseline; }}
.activity-table tbody tr:last-child td {{ border-bottom: 0; }}
.activity-table thead th {{ position: sticky; top: 0; z-index: 1; background: var(--head); font-weight: 600; font-size: .78rem; text-transform: uppercase; letter-spacing: .03em; color: var(--skip); }}
.activity-table tbody tr:hover td {{ background: color-mix(in srgb, var(--head) 60%, transparent); }}
.activity-table a {{ color: var(--fg); text-decoration: none; }}
.activity-table a:hover {{ text-decoration: underline; }}
.activity-table .a-repo a {{ font-weight: 500; }}
.activity-table .a-num a {{ color: var(--skip); font: 600 .82rem/1 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }}
.activity-table .a-title {{ max-width: 40rem; }}
.kind {{ display: inline-block; font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .03em; padding: .05rem .45rem; border-radius: 999px; }}
.kind.pr {{ color: var(--ok); border: 1px solid color-mix(in srgb, var(--ok) 55%, transparent); }}
.kind.issue {{ color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 55%, transparent); }}
.activity-table .empty {{ color: var(--skip); font-style: italic; text-align: center; }}
</style>
"""

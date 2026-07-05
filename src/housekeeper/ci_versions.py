"""Which version of the fleet's shared CI each repo pins — surfaced in the dashboard.

Both tools ship as GitHub Actions (`zmaril/housekeeping@REF`, `zmaril/straitjacket@REF`)
or, for straitjacket, a `curl … install.sh` line. Reading the ref a repo pins shows
fleet drift at a glance: who's on an old pin, who floats on `main`."""

from __future__ import annotations

import re
from pathlib import Path

_HK = re.compile(r"zmaril/housekeeping@(\S+)")
_SJ = re.compile(r"zmaril/straitjacket@(\S+)")
_SJ_INSTALL = re.compile(r"straitjacket/\S*install\.sh")


def ci_versions(repo: str, workflows: str) -> dict[str, str]:
    """The housekeeping-action and straitjacket refs a repo pins, from the concatenated
    text of its workflow files. '' = not used; 'self' = the repo IS that tool (runs from
    source); 'install.sh' = tracks the latest release via the install script."""
    repo_l = repo.lower()
    hk = "self" if repo_l.endswith("/housekeeping") else ""
    sj = "self" if repo_l.endswith("/straitjacket") else ""
    if not hk:
        m = _HK.search(workflows)
        if m:
            hk = m.group(1)
    if not sj:
        m = _SJ.search(workflows)
        if m:
            sj = m.group(1)
        elif _SJ_INSTALL.search(workflows):
            sj = "install.sh"
    return {"housekeeping": hk, "straitjacket": sj}


def read_workflows(workdir: Path | None) -> str:
    """Concatenate the repo's workflow YAML, or '' if there's no clone / no workflows."""
    if not workdir:
        return ""
    wf = workdir / ".github" / "workflows"
    if not wf.is_dir():
        return ""
    parts = [
        p.read_text(errors="ignore")
        for p in sorted(wf.iterdir())
        if p.is_file() and p.suffix.lower() in (".yml", ".yaml")
    ]
    return "\n".join(parts)

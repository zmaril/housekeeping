"""Homepage URL is set and reachable; external links in the README resolve."""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from ..context import RepoContext
from ..registry import check, failed, passed
from .readme import find_readme

EXTERNAL_LINK = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
MAX_LINKS = 10
TIMEOUT = 10
UA = "housekeeper/1.0 (+https://github.com/zmaril/housekeeping)"


def fetch_status(url: str) -> int | str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return type(e).__name__


@check("website", needs=("clone", "api"))
def website(ctx: RepoContext):
    expected = ctx.config.section("website").get("url")
    homepage = expected or ctx.repo_info.get("homepage") or ""

    problems = []
    if not homepage:
        problems.append("no homepage URL set on the repo")
    else:
        status = fetch_status(homepage)
        if status != 200:
            problems.append(f"homepage {homepage} → {status}")

    readme_path = find_readme(ctx.workdir)
    broken = []
    checked = 0
    if readme_path:
        links = list(dict.fromkeys(EXTERNAL_LINK.findall(readme_path.read_text(errors="replace"))))
        for url in links[:MAX_LINKS]:
            checked += 1
            status = fetch_status(url)
            if status != 200:
                broken.append(f"{url} → {status}")
        if len(links) > MAX_LINKS:
            checked_note = f"only first {MAX_LINKS} of {len(links)} README links checked"
        else:
            checked_note = ""
    else:
        checked_note = "no README to check links in"
    if broken:
        problems.append(f"broken README links: {'; '.join(broken)}")

    if problems:
        note = checked_note
        if not homepage:
            note = ('set a homepage on the repo, or add [website] url = "..." or '
                    'checks.website = "off" to .housekeeping.toml' + (f"; {note}" if note else ""))
        return failed("; ".join(problems), note)
    return passed(f"homepage {homepage} reachable; {checked} README link(s) ok", checked_note)

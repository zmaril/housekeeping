"""LICENSE file present and GitHub detects it."""

from __future__ import annotations

from pathlib import Path

from ..context import RepoContext, run
from ..fixing import apply_file_fix
from ..registry import check, failed, fix_for, passed

CANDIDATES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "UNLICENSE")


def license_file(workdir: Path) -> Path | None:
    for name in CANDIDATES:
        if (workdir / name).is_file():
            return workdir / name
    return None


@check("license", needs=("clone", "api"))
def license(ctx: RepoContext):
    path = license_file(ctx.workdir)
    detected = (ctx.repo_info.get("license") or {}).get("spdx_id")
    if path and detected and detected != "NOASSERTION":
        return passed(f"{path.name} present, GitHub detects {detected}")
    if path:
        return passed(f"{path.name} present",
                      note="GitHub hasn't classified it (fine for nonstandard text)")
    return failed("no LICENSE file")


MIT = """\
MIT License

Copyright (c) {year} {name}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


@fix_for("license")
def fix(ctx: RepoContext):
    import datetime

    who = run(["git", "config", "user.name"], cwd=ctx.workdir).stdout.strip() or "the author"
    year = datetime.date.today().year

    def write(workdir: Path) -> list[Path]:
        target = workdir / "LICENSE"
        target.write_text(MIT.format(year=year, name=who))
        return [target]

    apply_file_fix(
        ctx, "license",
        describe=f"add an MIT LICENSE (copyright {year} {who})",
        why="without a license the default is all-rights-reserved copyright — nobody "
            "can legally use, modify, or redistribute the code, however public the repo",
        write_changes=write,
        commit_message="chore: add MIT license",
    )

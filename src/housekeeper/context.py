"""RepoContext: everything a check needs — gh wrapper, clone cache, ecosystem detection."""

from __future__ import annotations

import json
import re
import subprocess
from functools import cached_property
from pathlib import Path
from typing import Any

from .config import Config

# Ecosystem/language knowledge lives in one place (languages.py). Re-exported here
# because that's where checks and tests have always imported Ecosystem from.
from .languages import Ecosystem, detect_ecosystems  # noqa: F401

CACHE_DIR = Path.home() / ".cache" / "housekeeping"


class GhError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status


def run(
    cmd: list[str], cwd: Path | None = None, input_data: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, input=input_data, capture_output=True, text=True
    )


class RepoContext:
    def __init__(self, repo: str, workdir: Path | None = None):
        self.repo = repo  # "owner/name"
        self._workdir = workdir
        self._config: Config | None = None

    # ---- GitHub API (via gh, which already holds auth) ----

    def api(
        self,
        path: str,
        method: str = "GET",
        input: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        args = ["api", path]
        # gh flips to POST when -f/-F fields are present unless the method is
        # forced — always force it so a GET with params can never mutate.
        if method != "GET" or params:
            args += ["-X", method]
        for key, value in (params or {}).items():
            args += ["-f" if isinstance(value, str) else "-F", f"{key}={value}"]
        input_data = None
        if input is not None:
            args += ["--input", "-"]
            input_data = json.dumps(input)
        proc = run(["gh"] + args, input_data=input_data)
        if proc.returncode != 0:
            match = re.search(r"HTTP (\d{3})", proc.stderr)
            status = int(match.group(1)) if match else None
            raise GhError(status, proc.stderr.strip() or f"gh api {path} failed")
        if not proc.stdout.strip():
            return True  # 204-style success with no body
        return json.loads(proc.stdout)

    def try_api(self, path: str, none_on: tuple[int, ...] = (404,), **kwargs) -> Any:
        try:
            return self.api(path, **kwargs)
        except GhError as e:
            if e.status in none_on:
                return None
            raise

    @cached_property
    def repo_info(self) -> dict:
        return self.api(f"repos/{self.repo}")

    @property
    def default_branch(self) -> str:
        return self.repo_info["default_branch"]

    @property
    def visibility(self) -> str:
        return "private" if self.repo_info["private"] else "public"

    # ---- Working copy ----

    @property
    def workdir(self) -> Path:
        if self._workdir is None:
            raise RuntimeError(
                "check declared needs=('clone',) but no workdir was prepared"
            )
        return self._workdir

    @property
    def has_workdir(self) -> bool:
        return self._workdir is not None

    def ensure_workdir(self) -> Path:
        if self._workdir is not None:
            return self._workdir
        local = local_checkout_for(self.repo)
        if local is not None:
            self._workdir = local
            return local
        dest = CACHE_DIR / self.repo
        if (dest / ".git").exists():
            fetch = run(
                ["git", "fetch", "--depth=1", "origin", self.default_branch], cwd=dest
            )
            if fetch.returncode == 0:
                run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            proc = run(
                ["gh", "repo", "clone", self.repo, str(dest), "--", "--depth", "1"]
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"clone of {self.repo} failed: {proc.stderr.strip()}"
                )
        self._workdir = dest
        return dest

    @property
    def workdir_is_cache(self) -> bool:
        return self.has_workdir and CACHE_DIR in self.workdir.parents

    # ---- Shared detection & config ----

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = Config.load(self._workdir)
        return self._config

    @cached_property
    def ecosystems(self) -> list[Ecosystem]:
        return detect_ecosystems(self.workdir)


def local_checkout_for(repo: str) -> Path | None:
    """If the cwd is a checkout of `repo`, use it instead of a cache clone."""
    proc = run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd())
    if proc.returncode != 0:
        return None
    top = Path(proc.stdout.strip())
    remote = run(["git", "remote", "get-url", "origin"], cwd=top)
    if remote.returncode != 0:
        return None
    parsed = parse_repo_url(remote.stdout.strip())
    return top if parsed and parsed.lower() == repo.lower() else None


def repo_from_cwd() -> str | None:
    proc = run(["git", "remote", "get-url", "origin"], cwd=Path.cwd())
    if proc.returncode != 0:
        return None
    return parse_repo_url(proc.stdout.strip())


def parse_repo_url(url: str) -> str | None:
    match = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{match.group(1)}/{match.group(2)}" if match else None

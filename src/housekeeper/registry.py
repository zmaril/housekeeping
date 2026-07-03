"""Check registry: every check is a module in checks/ that registers here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .context import RepoContext


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class Result:
    status: Status
    details: str
    note: str = ""


def passed(details: str, note: str = "") -> Result:
    return Result(Status.PASS, details, note)


def failed(details: str, note: str = "") -> Result:
    return Result(Status.FAIL, details, note)


def skipped(details: str, note: str = "") -> Result:
    return Result(Status.SKIP, details, note)


@dataclass
class Check:
    name: str
    needs: tuple[str, ...]  # any of: "clone", "api", "admin"
    run: Callable[[RepoContext], Result]
    fix: Callable[[RepoContext], None] | None = None

    @property
    def fixable(self) -> bool:
        return self.fix is not None


CHECKS: dict[str, Check] = {}


def check(name: str, needs: tuple[str, ...] = ("api",)):
    def register(func: Callable[[RepoContext], Result]):
        CHECKS[name] = Check(name=name, needs=tuple(needs), run=func)
        return func

    return register


def fix_for(name: str):
    def register(func: Callable[[RepoContext], None]):
        CHECKS[name].fix = func
        return func

    return register

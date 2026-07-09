from types import SimpleNamespace

import housekeeper.checks.allow_auto_merge as mod
from housekeeper.checks.allow_auto_merge import allow_auto_merge, fix
from housekeeper.config import Config
from housekeeper.context import GhError
from housekeeper.registry import Status


def ctx(repo_info, overrides=None):
    return SimpleNamespace(
        repo="o/r",
        repo_info=repo_info,
        config=Config(overrides or {}),
    )


def test_off_and_declared_off_passes():
    result = allow_auto_merge(ctx({"allow_auto_merge": False}))
    assert result.status == Status.PASS
    assert "off" in result.details


def test_on_but_declared_off_fails():
    result = allow_auto_merge(ctx({"allow_auto_merge": True}))
    assert result.status == Status.FAIL
    assert "on" in result.details and "off" in result.details


def test_off_but_declared_on_fails():
    result = allow_auto_merge(
        ctx({"allow_auto_merge": False}, {"allow-auto-merge": {"enabled": True}})
    )
    assert result.status == Status.FAIL
    assert "off" in result.details and "on" in result.details


def test_on_and_declared_on_passes():
    result = allow_auto_merge(
        ctx({"allow_auto_merge": True}, {"allow-auto-merge": {"enabled": True}})
    )
    assert result.status == Status.PASS
    assert "on" in result.details


def test_setting_absent_skips():
    result = allow_auto_merge(ctx({}))
    assert result.status == Status.SKIP


def test_fix_403_is_handled(monkeypatch):
    monkeypatch.setattr(mod, "confirm", lambda *a, **k: True)

    def api(path, method=None, input=None):
        raise GhError(403, "forbidden")

    fixctx = SimpleNamespace(
        repo="o/r",
        repo_info={"allow_auto_merge": True},
        config=Config({}),
        api=api,
    )
    # default preference is off; setting is on -> fix tries to PATCH, hits 403.
    fix(fixctx)  # returns without raising


def test_fix_patches_to_wanted(monkeypatch):
    monkeypatch.setattr(mod, "confirm", lambda *a, **k: True)
    calls = []

    def api(path, method=None, input=None):
        calls.append((path, method, input))

    fixctx = SimpleNamespace(
        repo="o/r",
        repo_info={"allow_auto_merge": True},
        config=Config({}),
        api=api,
    )
    fix(fixctx)
    assert calls == [("repos/o/r", "PATCH", {"allow_auto_merge": False})]

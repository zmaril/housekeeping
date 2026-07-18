from types import SimpleNamespace

import housekeeper.checks.strict_status_checks as mod
from housekeeper.checks.strict_status_checks import fix, strict_status_checks
from housekeeper.context import GhError
from housekeeper.registry import Status


class FakeCtx:
    repo, default_branch = "o/r", "main"

    def __init__(
        self, rules=None, classic=None, visibility="public", allow_update=True
    ):
        self.visibility = visibility
        self._rules = rules
        self._classic = classic
        self.repo_info = {"allow_update_branch": allow_update}

    def try_api(self, path, none_on=(404,), **kw):
        if "/rules/branches/" in path:
            return self._rules
        if path.endswith("/protection/required_status_checks"):
            return self._classic
        return None


def _rsc_rule(strict):
    return {
        "type": "required_status_checks",
        "parameters": {"strict_required_status_checks_policy": strict},
    }


def test_strict_true_via_ruleset_passes():
    r = strict_status_checks(FakeCtx(rules=[_rsc_rule(True)]))
    assert r.status == Status.PASS
    assert "strict=true" in r.details


def test_strict_false_via_ruleset_fails():
    r = strict_status_checks(FakeCtx(rules=[_rsc_rule(False)]))
    assert r.status == Status.FAIL
    assert "stale" in r.details


def test_strict_true_via_classic_passes():
    r = strict_status_checks(FakeCtx(rules=None, classic={"strict": True}))
    assert r.status == Status.PASS


def test_both_none_public_fails():
    r = strict_status_checks(FakeCtx(rules=None, classic=None, visibility="public"))
    assert r.status == Status.FAIL
    assert "no required status checks configured" in r.details


def test_both_none_private_skips():
    r = strict_status_checks(FakeCtx(rules=None, classic=None, visibility="private"))
    assert r.status == Status.SKIP


def test_strict_true_but_allow_update_off_passes_with_note():
    r = strict_status_checks(FakeCtx(rules=[_rsc_rule(True)], allow_update=False))
    assert r.status == Status.PASS
    assert "allow_update_branch" in r.note


# ---- fix ----

RULESET = {
    "id": 42,
    "name": "protect",
    "target": "branch",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "enforcement": "active",
    "rules": [
        {"type": "deletion"},
        {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [{"context": "test"}],
                "strict_required_status_checks_policy": False,
            },
        },
    ],
}


def _fixctx(rulesets, full, calls):
    def api(path, method="GET", input=None, params=None):
        if path == "repos/o/r/rulesets" and method == "GET":
            return rulesets
        if path.startswith("repos/o/r/rulesets/") and method == "GET":
            return full
        calls.append((path, method, input))
        return True

    return SimpleNamespace(repo="o/r", default_branch="main", api=api)


def test_fix_sets_strict_and_allow_update(monkeypatch):
    monkeypatch.setattr(mod, "confirm", lambda *a, **k: True)
    calls = []
    fix(_fixctx([{"id": 42}], RULESET, calls))
    put = next(c for c in calls if c[1] == "PUT")
    assert put[0] == "repos/o/r/rulesets/42"
    rsc = next(r for r in put[2]["rules"] if r["type"] == "required_status_checks")
    assert rsc["parameters"]["strict_required_status_checks_policy"] is True
    patch = next(c for c in calls if c[1] == "PATCH")
    assert patch == ("repos/o/r", "PATCH", {"allow_update_branch": True})


def test_fix_403_is_handled(monkeypatch):
    monkeypatch.setattr(mod, "confirm", lambda *a, **k: True)

    def api(path, method="GET", input=None, params=None):
        if path == "repos/o/r/rulesets" and method == "GET":
            return [{"id": 42}]
        if path.startswith("repos/o/r/rulesets/") and method == "GET":
            return RULESET
        raise GhError(403, "forbidden")

    fixctx = SimpleNamespace(repo="o/r", default_branch="main", api=api)
    fix(fixctx)  # returns without raising


def test_fix_no_ruleset_refuses(monkeypatch):
    monkeypatch.setattr(mod, "confirm", lambda *a, **k: True)
    calls = []

    def api(path, method="GET", input=None, params=None):
        if path == "repos/o/r/rulesets" and method == "GET":
            return []
        calls.append((path, method, input))
        return True

    fix(SimpleNamespace(repo="o/r", default_branch="main", api=api))
    assert calls == []


def test_fix_no_required_status_checks_rule_refuses(monkeypatch):
    monkeypatch.setattr(mod, "confirm", lambda *a, **k: True)
    calls = []
    no_rsc = {**RULESET, "rules": [{"type": "deletion"}]}
    fix(_fixctx([{"id": 42}], no_rsc, calls))
    assert calls == []

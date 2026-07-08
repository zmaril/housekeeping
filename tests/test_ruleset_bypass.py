"""ruleset-bypass: gating rulesets must name a bypass actor, because rulesets
(unlike classic protection) ignore `gh pr merge --admin` without one."""

from housekeeper.checks.ruleset_bypass import ruleset_bypass
from housekeeper.registry import Status


class FakeCtx:
    repo = "o/r"

    def __init__(self, rulesets, details):
        self._rulesets = rulesets
        self._details = details

    def try_api(self, path, none_on=(404,), **kwargs):
        if path.endswith("/rulesets"):
            return self._rulesets
        ruleset_id = int(path.rsplit("/", 1)[1])
        return self._details.get(ruleset_id)


def rs(id, name="main", target="branch", enforcement="active"):
    return {"id": id, "name": name, "target": target, "enforcement": enforcement}


def detail(id, rule_types, bypass_actors, name="main"):
    return {
        "id": id,
        "name": name,
        "rules": [{"type": t} for t in rule_types],
        "bypass_actors": bypass_actors,
    }


def test_gating_ruleset_without_bypass_fails():
    ctx = FakeCtx(
        [rs(1)],
        {1: detail(1, ["pull_request", "required_status_checks"], [])},
    )
    r = ruleset_bypass(ctx)
    assert r.status == Status.FAIL
    assert "no bypass actor" in r.details
    assert "--admin" in r.note


def test_gating_ruleset_with_bypass_passes():
    ctx = FakeCtx(
        [rs(1)],
        {
            1: detail(
                1, ["pull_request"], [{"actor_id": 5, "actor_type": "RepositoryRole"}]
            )
        },
    )
    assert ruleset_bypass(ctx).status == Status.PASS


def test_non_gating_and_inactive_rulesets_dont_count():
    ctx = FakeCtx(
        [
            rs(1),  # active but only cosmetic rules
            rs(2, enforcement="disabled"),  # gating but off
            rs(3, target="tag"),  # not a branch ruleset
        ],
        {
            1: detail(1, ["deletion", "non_fast_forward"], []),
            2: detail(2, ["pull_request"], []),
            3: detail(3, ["pull_request"], []),
        },
    )
    r = ruleset_bypass(ctx)
    assert r.status == Status.SKIP
    assert "classic branch protection honors --admin" in r.note


def test_invisible_rulesets_skip():
    class Blind(FakeCtx):
        def try_api(self, path, none_on=(404,), **kwargs):
            return None

    r = ruleset_bypass(Blind([], {}))
    assert r.status == Status.SKIP
    assert "not visible" in r.details

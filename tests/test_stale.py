from housekeeper.checks.stale import stale
from housekeeper.registry import Status


class StaleCtx:
    repo = "o/r"
    default_branch = "main"

    def __init__(self, auto_delete, branches=(), merged=()):
        self.repo_info = (
            {} if auto_delete is None else {"delete_branch_on_merge": auto_delete}
        )
        self._branches = list(branches)
        self._merged = set(merged)

    def api(self, path, params=None):
        if path.endswith("/pulls"):
            return []
        if path.endswith("/branches"):
            return [{"name": n} for n in ["main", *self._branches]]
        raise AssertionError(path)

    def try_api(self, path, **kwargs):
        branch = path.split("...")[-1]
        return {"ahead_by": 0 if branch in self._merged else 2}


def test_auto_delete_off_is_a_problem():
    result = stale(StaleCtx(auto_delete=False))
    assert result.status == Status.FAIL
    assert "delete_branch_on_merge" in result.details


def test_auto_delete_invisible_is_only_a_note():
    result = stale(StaleCtx(auto_delete=None))
    assert result.status == Status.PASS
    assert "not visible" in result.note


def test_merged_branches_flagged():
    result = stale(StaleCtx(auto_delete=True, branches=["a", "b"], merged=["a"]))
    assert result.status == Status.FAIL
    assert "a" in result.details and "b" not in result.details.split("not deleted:")[1]

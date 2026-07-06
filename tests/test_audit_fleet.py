from housekeeper import cli


class M:
    def __init__(self, repo):
        self.repo = repo


def test_audit_fleet_preserves_order_and_isolates_errors(monkeypatch):
    def fake_audit(repo, only=None):
        if repo == "o/bad":
            raise cli.GhError(500, "boom")
        return {"repo": repo}

    monkeypatch.setattr(cli, "audit", fake_audit)
    members = [M("o/a"), M("o/bad"), M("o/c")]
    out = cli.audit_fleet(members)
    # order matches input; the unreachable member is None, not dropped
    assert [p and p["repo"] for p in out] == ["o/a", None, "o/c"]


def test_audit_fleet_runs_members_concurrently(monkeypatch):
    import threading
    import time

    barrier = threading.Barrier(3, timeout=5)

    def fake_audit(repo, only=None):
        # if calls were serial this barrier would time out; concurrency lets it trip
        barrier.wait()
        return {"repo": repo}

    monkeypatch.setattr(cli, "audit", fake_audit)
    members = [M(f"o/{i}") for i in range(3)]
    start = time.monotonic()
    out = cli.audit_fleet(members)
    assert [p["repo"] for p in out] == ["o/0", "o/1", "o/2"]
    assert time.monotonic() - start < 5  # tripped, didn't time out


def test_audit_fleet_empty():
    assert cli.audit_fleet([]) == []

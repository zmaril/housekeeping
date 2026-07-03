from types import SimpleNamespace

from housekeeper.checks.action_badge import action_badge, marketplace_slug
from housekeeper.registry import Status

ACTION = 'name: Powderworks Housekeeping\ndescription: x\nruns: {using: composite, steps: []}\n'
BADGE_LINK = "https://github.com/marketplace/actions/powderworks-housekeeping"


def ctx_for(tmp_path, visibility="public"):
    return SimpleNamespace(workdir=tmp_path, visibility=visibility)


def test_skips_without_an_action(tmp_path):
    assert action_badge(ctx_for(tmp_path)).status == Status.SKIP


def test_skips_on_private_repos(tmp_path):
    (tmp_path / "action.yml").write_text(ACTION)
    assert action_badge(ctx_for(tmp_path, visibility="private")).status == Status.SKIP


def test_fails_without_badge(tmp_path):
    (tmp_path / "action.yml").write_text(ACTION)
    (tmp_path / "README.md").write_text("# thing\n\nwords\n")
    result = action_badge(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "Marketplace badge" in result.details


def test_passes_with_marketplace_link(tmp_path):
    (tmp_path / "action.yml").write_text(ACTION)
    (tmp_path / "README.md").write_text(f"# thing\n\n[badge]({BADGE_LINK})\n")
    assert action_badge(ctx_for(tmp_path)).status == Status.PASS


def test_slug_derivation(tmp_path):
    (tmp_path / "action.yml").write_text(ACTION)
    assert marketplace_slug(tmp_path / "action.yml") == "powderworks-housekeeping"

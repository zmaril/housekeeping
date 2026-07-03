import pytest

from housekeeper.config import Config


def test_defaults():
    config = Config()
    assert config.severity("branch-protection", "public") == "required"
    assert config.severity("stale", "public") == "recommended"


def test_private_profile_softens_audience_facing_checks():
    config = Config()
    for check in ("website", "license", "changelog", "readme"):
        assert config.severity(check, "private") == "recommended"
        assert config.severity(check, "public") == "required"
    assert config.severity("repo-meta", "private") == "off"


def test_private_profile_keeps_engineering_hygiene():
    config = Config()
    for check in ("ci-exists", "lockfiles", "dependabot", "secret-scanning"):
        assert config.severity(check, "private") == "required"


def test_repo_override_wins():
    config = Config({"checks": {"website": "off"}})
    assert config.severity("website", "public") == "off"


def test_invalid_severity_raises():
    config = Config({"checks": {"website": "nope"}})
    with pytest.raises(ValueError):
        config.severity("website", "public")


def test_section():
    config = Config({"website": {"url": "https://example.dev"}})
    assert config.section("website")["url"] == "https://example.dev"
    assert config.section("missing") == {}


def test_load_from_workdir(tmp_path):
    (tmp_path / ".housekeeping.toml").write_text('[checks]\nstale = "off"\n')
    config = Config.load(tmp_path)
    assert config.severity("stale", "public") == "off"
    assert Config.load(None).severity("stale", "public") == "recommended"

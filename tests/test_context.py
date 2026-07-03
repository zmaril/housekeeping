from housekeeper.context import detect_ecosystems, parse_repo_url


def test_parse_repo_url_variants():
    assert parse_repo_url("https://github.com/zmaril/entl.git") == "zmaril/entl"
    assert parse_repo_url("https://github.com/zmaril/entl") == "zmaril/entl"
    assert parse_repo_url("git@github.com:zmaril/entl.git") == "zmaril/entl"
    assert parse_repo_url("https://gitlab.com/x/y") is None
    assert parse_repo_url("not a url") is None


def test_detect_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]")
    ecosystems = detect_ecosystems(tmp_path)
    assert [e.name for e in ecosystems] == ["cargo"]
    assert ecosystems[0].lockfile == "Cargo.lock"


def test_detect_bun_over_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "bun.lock").write_text("")
    assert [e.name for e in detect_ecosystems(tmp_path)] == ["bun"]


def test_detect_npm_without_lockfile(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    ecosystems = detect_ecosystems(tmp_path)
    assert ecosystems[0].name == "npm"
    assert ecosystems[0].lockfile == "package-lock.json"


def test_detect_uv_and_actions(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci")
    names = {e.name for e in detect_ecosystems(tmp_path)}
    assert names == {"uv", "github-actions"}


def test_dependabot_alternatives():
    from housekeeper.context import Ecosystem

    bun = Ecosystem("bun", "package.json", "bun.lock", "bun", ("npm",))
    assert {"npm"} & {bun.dependabot, *bun.dependabot_alts}

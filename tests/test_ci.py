import yaml

from housekeeper.checks.ci import LANG_SIGNALS, run_commands, triggers


def test_triggers_handles_yaml_on_as_true_key():
    # YAML 1.1 parses a bare `on:` key as boolean True.
    workflow = yaml.safe_load("on:\n  push:\n  pull_request:\njobs: {}\n")
    assert triggers(workflow) == {"push", "pull_request"}


def test_triggers_string_and_list():
    assert triggers({"on": "push"}) == {"push"}
    assert triggers({"on": ["push", "workflow_dispatch"]}) == {
        "push",
        "workflow_dispatch",
    }


def test_run_commands_collects_steps():
    workflow = {
        "jobs": {
            "test": {
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"run": "cargo clippy -- -D warnings"},
                    {"name": "Run tests", "run": "cargo test"},
                ]
            }
        }
    }
    commands = run_commands(workflow)
    assert LANG_SIGNALS["rust"]["test"].search(commands)
    assert LANG_SIGNALS["rust"]["lint"].search(commands)


def test_signals_do_not_match_unrelated():
    assert not LANG_SIGNALS["rust"]["test"].search("cargo build --release")
    assert not LANG_SIGNALS["js"]["lint"].search("curl -fsSL https://example.com | sh")


def test_combined_tools_satisfy_lint_and_fmt():
    assert LANG_SIGNALS["js"]["lint"].search("biome check src")
    assert LANG_SIGNALS["js"]["fmt"].search("biome check src")
    assert LANG_SIGNALS["ruby"]["lint"].search("bundle exec rubocop")
    assert LANG_SIGNALS["ruby"]["fmt"].search("bundle exec rubocop")
    # but ruff check is lint-only; ruff format is fmt-only
    assert LANG_SIGNALS["python"]["lint"].search("uv run ruff check .")
    assert not LANG_SIGNALS["python"]["fmt"].search("uv run ruff check .")
    assert LANG_SIGNALS["python"]["fmt"].search("uv run ruff format --check .")

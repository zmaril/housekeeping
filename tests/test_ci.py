import yaml

from housekeeper.checks.ci import LINT_PATTERN, TEST_PATTERN, run_commands, triggers


def test_triggers_handles_yaml_on_as_true_key():
    # YAML 1.1 parses a bare `on:` key as boolean True.
    workflow = yaml.safe_load("on:\n  push:\n  pull_request:\njobs: {}\n")
    assert triggers(workflow) == {"push", "pull_request"}


def test_triggers_string_and_list():
    assert triggers({"on": "push"}) == {"push"}
    assert triggers({"on": ["push", "workflow_dispatch"]}) == {"push", "workflow_dispatch"}


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
    assert TEST_PATTERN.search(commands)
    assert LINT_PATTERN.search(commands)


def test_patterns_do_not_match_unrelated():
    assert not TEST_PATTERN.search("cargo build --release")
    assert not LINT_PATTERN.search("curl -fsSL https://example.com | sh")

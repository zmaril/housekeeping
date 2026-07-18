import yaml

from housekeeper.checks.ci import run_commands, triggers
from housekeeper.languages import LANGUAGES


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
    assert LANGUAGES["rust"].test.search(commands)
    assert LANGUAGES["rust"].lint.search(commands)


def test_signals_do_not_match_unrelated():
    assert not LANGUAGES["rust"].test.search("cargo build --release")
    assert not LANGUAGES["js"].lint.search("curl -fsSL https://example.com | sh")


def test_combined_tools_satisfy_lint_and_fmt():
    assert LANGUAGES["js"].lint.search("biome check src")
    assert LANGUAGES["js"].fmt.search("biome check src")
    assert LANGUAGES["ruby"].lint.search("bundle exec rubocop")
    assert LANGUAGES["ruby"].fmt.search("bundle exec rubocop")
    # but ruff check is lint-only; ruff format is fmt-only
    assert LANGUAGES["python"].lint.search("uv run ruff check .")
    assert not LANGUAGES["python"].fmt.search("uv run ruff check .")
    assert LANGUAGES["python"].fmt.search("uv run ruff format --check .")


def test_ruby_test_signal_recognizes_ruby_itest_idiom():
    # Fleet ruby bindings run their tests as `bundle exec ruby -Itest test/...`.
    assert LANGUAGES["ruby"].test.search("bundle exec ruby -Itest test/test_entl.rb")
    # ...but a bare ruby invocation with no test file must not count.
    assert not LANGUAGES["ruby"].test.search("ruby -e 'puts 1'")

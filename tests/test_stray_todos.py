import subprocess
from types import SimpleNamespace

from housekeeper.checks.stray_todos import stray_todos
from housekeeper.config import Config
from housekeeper.registry import Status


def ctx_for(tmp_path, files, overrides=None):
    """Write `files` (path -> content), git-track them, return a ctx."""
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return SimpleNamespace(workdir=tmp_path, config=Config(overrides))


def test_flags_a_todo_marker_in_code(tmp_path):
    r = stray_todos(ctx_for(tmp_path, {"src/app.py": "x = 1  # TODO: fix this\n"}))
    assert r.status == Status.FAIL
    assert "src/app.py" in r.details


def test_prose_mention_of_todo_is_not_flagged(tmp_path):
    ctx = ctx_for(
        tmp_path, {"README.md": "See the todo file (todo.txt) for the plan.\n"}
    )
    assert stray_todos(ctx).status == Status.PASS


def test_markers_in_the_todo_file_are_fine(tmp_path):
    ctx = ctx_for(tmp_path, {"todo.txt": "TODO: ship it\nFIXME: later\n"})
    assert stray_todos(ctx).status == Status.PASS


def test_placeholder_heading_is_flagged(tmp_path):
    ctx = ctx_for(tmp_path, {"README.md": "# Tool\n\n## TODO\n\nwrite this\n"})
    assert stray_todos(ctx).status == Status.FAIL


def test_fixme_wip_lowercase_across_files(tmp_path):
    r = stray_todos(ctx_for(tmp_path, {"a.py": "# fixme: x\n", "b.rs": "// wip: y\n"}))
    assert r.status == Status.FAIL
    assert "a.py" in r.details and "b.rs" in r.details


def test_ignore_config_excludes_paths(tmp_path):
    ctx = ctx_for(
        tmp_path,
        {"tests/fixture.py": "# TODO: intentional test data\n"},
        {"stray-todos": {"ignore": ["tests/"]}},
    )
    assert stray_todos(ctx).status == Status.PASS


def test_identifier_lookalikes_not_matched(tmp_path):
    # todoList / TODO_STEMS / "a todo." are words in code, not markers.
    ctx = ctx_for(
        tmp_path,
        {"x.py": "todoList = []\nTODO_STEMS = {'todo'}\n# arrives as a todo.\n"},
    )
    assert stray_todos(ctx).status == Status.PASS


def test_untracked_files_are_not_scanned(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "tracked.py").write_text("ok = 1\n")
    (tmp_path / "cache.py").write_text("# TODO: in an untracked file\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "src/tracked.py"], cwd=tmp_path, check=True)
    ctx = SimpleNamespace(workdir=tmp_path, config=Config(None))
    assert stray_todos(ctx).status == Status.PASS

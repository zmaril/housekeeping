from types import SimpleNamespace

from housekeeper.checks.readme import readme
from housekeeper.registry import Status

GOOD = (
    "# thing\n\nA tool that does the thing, for people who need things done.\n\n"
    "## Install\n\n```sh\ncargo install thing\n```\n\n"
    "## Usage\n\n```sh\nthing --help\n```\n\n"
    "See [the docs](docs/guide.md) for more.\n\n## License\n\nMIT\n\n"
) + ("filler words to clear the minimum count. " * 20)


def ctx_for(tmp_path):
    return SimpleNamespace(workdir=tmp_path)


def test_no_readme_fails(tmp_path):
    assert readme(ctx_for(tmp_path)).status == Status.FAIL


def test_good_readme_passes(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("guide")
    (tmp_path / "README.md").write_text(GOOD)
    result = readme(ctx_for(tmp_path))
    assert result.status == Status.PASS, result.details


def test_thin_readme_lists_all_problems(tmp_path):
    (tmp_path / "README.md").write_text("# thing\n\nit does stuff\n")
    result = readme(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    for problem in ("words", "install", "usage", "license"):
        assert problem in result.details


def test_broken_relative_link_flagged(tmp_path):
    (tmp_path / "README.md").write_text(GOOD.replace("docs/guide.md", "docs/gone.md"))
    result = readme(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "docs/gone.md" in result.details

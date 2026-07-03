from types import SimpleNamespace

from housekeeper.checks.readme import readme
from housekeeper.registry import Status

GOOD = (
    "# thing\n\nA tool that does the thing, for people who need things done.\n\n"
    "## Install\n\n```sh\ncargo install thing\n```\n\n"
    "## Usage\n\n```sh\nthing --help\n```\n\n"
    "See [the docs](docs/guide.md) for more.\n\n"
    "## Contributing\n\nIssues welcome.\n\n## License\n\nMIT\n\n"
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
    for problem in ("words", "install", "usage", "License section", "Contributing section"):
        assert problem in result.details


def test_license_in_prose_does_not_count(tmp_path):
    # the old substring floor was satisfied by an incidental "license" in prose
    text = GOOD.replace("## License\n\nMIT\n\n", "it is license-adjacent software\n\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("guide")
    (tmp_path / "README.md").write_text(text)
    result = readme(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "License section" in result.details


def test_heading_word_families_count(tmp_path):
    text = GOOD.replace("## Contributing\n\nIssues welcome.\n\n", "### Contributions\n\nsend them\n\n")
    text = text.replace("## License\n\nMIT\n\n", "# Licensing\n\nMIT\n\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("guide")
    (tmp_path / "README.md").write_text(text)
    assert readme(ctx_for(tmp_path)).status == Status.PASS


def test_broken_relative_link_flagged(tmp_path):
    (tmp_path / "README.md").write_text(GOOD.replace("docs/guide.md", "docs/gone.md"))
    result = readme(ctx_for(tmp_path))
    assert result.status == Status.FAIL
    assert "docs/gone.md" in result.details

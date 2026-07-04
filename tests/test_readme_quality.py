from conftest import Ctx

from housekeeper.checks.readme_quality import readme_quality
from housekeeper.registry import Status


def test_passes_with_code_and_no_placeholders(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Tool\n\nDoes a thing.\n\n## Usage\n\n```sh\ntool run\n```\n"
    )
    assert readme_quality(Ctx(tmp_path)).status == Status.PASS


def test_fails_without_a_code_block(tmp_path):
    (tmp_path / "README.md").write_text("# Tool\n\nAll prose, no example to copy.\n")
    r = readme_quality(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "code" in r.details


def test_fails_on_placeholder_heading(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Tool\n\n```sh\ntool run\n```\n\n## TODO\n\nwrite this\n"
    )
    r = readme_quality(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "TODO" in r.details


def test_skips_when_no_readme(tmp_path):
    assert readme_quality(Ctx(tmp_path)).status == Status.SKIP

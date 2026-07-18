"""repo-meta reconciles the README-declared description/topics against GitHub."""

from types import SimpleNamespace

from housekeeper.checks.repo_meta import read_markers, repo_meta
from housekeeper.config import Config
from housekeeper.registry import Status

DESC = "A crude weapon for our barbaric age."
TOPICS = ["cli", "powderworks", "rust"]


def write_readme(tmp_path, body):
    (tmp_path / "README.md").write_text(body)


def markers_readme(description=DESC, topics=TOPICS):
    return (
        f"<!-- housekeeper:description {description} -->\n"
        f"<!-- housekeeper:topics {', '.join(topics)} -->\n"
        "# demo\n\nProse.\n"
    )


def ctx(tmp_path, repo_info):
    return SimpleNamespace(workdir=tmp_path, repo_info=repo_info, config=Config())


def test_markers_match_github_passes(tmp_path):
    write_readme(tmp_path, markers_readme())
    result = repo_meta(
        ctx(
            tmp_path,
            {"description": DESC, "topics": list(TOPICS), "has_issues": True},
        )
    )
    assert result.status == Status.PASS
    assert "3 topics in sync" in result.details


def test_description_mismatch_fails(tmp_path):
    write_readme(tmp_path, markers_readme())
    result = repo_meta(
        ctx(
            tmp_path,
            {
                "description": "Something else.",
                "topics": list(TOPICS),
                "has_issues": True,
            },
        )
    )
    assert result.status == Status.FAIL
    assert "description out of sync" in result.details


def test_topics_mismatch_fails(tmp_path):
    write_readme(tmp_path, markers_readme())
    result = repo_meta(
        ctx(
            tmp_path,
            {"description": DESC, "topics": ["cli", "rust"], "has_issues": True},
        )
    )
    assert result.status == Status.FAIL
    assert "topics out of sync" in result.details


def test_missing_markers_fails_with_adoption_nudge(tmp_path):
    write_readme(tmp_path, "# demo\n\nNo markers here.\n")
    result = repo_meta(
        ctx(
            tmp_path,
            {"description": DESC, "topics": list(TOPICS), "has_issues": True},
        )
    )
    assert result.status == Status.FAIL
    assert "no <!-- housekeeper:description" in result.details
    assert "no <!-- housekeeper:topics" in result.details


def test_invalid_topic_fails(tmp_path):
    write_readme(tmp_path, markers_readme(topics=["Foo_Bar"]))
    result = repo_meta(
        ctx(
            tmp_path,
            {"description": DESC, "topics": ["foo_bar"], "has_issues": True},
        )
    )
    assert result.status == Status.FAIL
    assert "invalid topics" in result.details


def test_too_many_topics_fails(tmp_path):
    many = [f"topic-{i}" for i in range(21)]
    write_readme(tmp_path, markers_readme(topics=many))
    result = repo_meta(
        ctx(tmp_path, {"description": DESC, "topics": many, "has_issues": True})
    )
    assert result.status == Status.FAIL
    assert "too many topics" in result.details


def test_issues_disabled_fails(tmp_path):
    write_readme(tmp_path, markers_readme())
    result = repo_meta(
        ctx(
            tmp_path,
            {"description": DESC, "topics": list(TOPICS), "has_issues": False},
        )
    )
    assert result.status == Status.FAIL
    assert "issues disabled" in result.details


def test_read_markers_parses_and_normalizes():
    markers = read_markers(
        "<!-- housekeeper:description  One-line tagline goes here.  -->\n"
        "<!-- housekeeper:topics Rust, CLI ,, codegen -->\n"
        "# title\n"
    )
    assert markers["description"] == "One-line tagline goes here."
    assert markers["topics"] == ["rust", "cli", "codegen"]


def test_read_markers_absent():
    assert read_markers("# title\n\nNo markers.\n") == {}

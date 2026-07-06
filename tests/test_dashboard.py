from housekeeper.config import Config
from housekeeper.dashboard import logo_url, render_document, render_matrix


class M:
    def __init__(self, repo):
        self.repo = repo


def payload(repo, results, logo=""):
    return {"repo": repo, "visibility": "public", "logo": logo, "results": results}


def row(check, status, severity="required"):
    return {
        "check": check,
        "status": status,
        "severity": severity,
        "details": f"{check} detail",
        "note": "",
        "fixable": False,
    }


def test_logo_url_passthrough_and_path_resolution():
    assert logo_url("o/r", "https://x.test/l.png") == "https://x.test/l.png"
    assert (
        logo_url("o/r", "assets/logo.svg")
        == "https://raw.githubusercontent.com/o/r/HEAD/assets/logo.svg"
    )
    assert (
        logo_url("o/r", "/assets/logo.svg")
        == "https://raw.githubusercontent.com/o/r/HEAD/assets/logo.svg"
    )
    assert logo_url("o/r", "") == ""


def test_config_logo_optional_and_not_unknown():
    cfg = Config({"logo": "assets/logo.png"})
    assert cfg.logo == "assets/logo.png"
    # logo is allow-listed, not surfaced as an unknown config key.
    assert cfg.unknown_keys({"branch-protection"}) == []
    assert Config({}).logo == ""


def test_matrix_has_a_cell_per_repo_per_check():
    members = [M("o/a"), M("o/b")]
    payloads = [
        payload(
            "o/a",
            [row("branch-protection", "pass"), row("license", "fail")],
            logo="https://x.test/a.png",
        ),
        payload("o/b", [row("branch-protection", "pass"), row("license", "skip")]),
    ]
    out = render_matrix("myfleet", members, payloads)
    assert "myfleet" in out
    assert ">a<" in out and ">b<" in out  # repo short names
    assert 'src="https://x.test/a.png"' in out  # a's logo rendered
    assert "✓" in out and "✗" in out and "–" in out  # pass / fail / skip glyphs
    # column headers for the checks present
    assert "branch-protection" in out and "license" in out


def test_recommended_failure_renders_as_warn():
    members = [M("o/a")]
    payloads = [payload("o/a", [row("ci-scoped", "fail", severity="recommended")])]
    out = render_matrix("f", members, payloads)
    assert 'class="warn"' in out
    assert 'class="bad"' not in out  # a recommended fail is a warn, not a hard fail


def test_unreachable_member_rendered():
    out = render_matrix("f", [M("o/a")], [None])
    assert "unreachable" in out


def test_ci_version_rows_and_repeated_footer():
    members = [M("o/a")]
    payloads = [payload("o/a", [row("license", "pass")])]
    payloads[0]["ci_versions"] = {"housekeeping": "v1", "straitjacket": "v0.2.3"}
    out = render_matrix("f", members, payloads)
    assert "housekeeping CI" in out and "straitjacket CI" in out  # the two meta rows
    assert "v0.2.3" in out  # the pinned straitjacket ref is shown
    # repo header (name wrapped in a <span>) repeated in thead and tfoot
    assert "<tfoot>" in out and out.count(">a</span>") == 2


def test_activity_table_lists_prs_and_issues_with_repo_column():
    members = [M("o/a"), M("o/b")]
    pa = payload("o/a", [row("license", "pass")])
    pa["activity"] = {
        "issues": [{"number": 7, "title": "a bug", "url": "https://x.test/i/7"}],
        "pulls": [{"number": 3, "title": "a fix", "url": "https://x.test/p/3"}],
    }
    pb = payload("o/b", [row("license", "pass")])
    pb["activity"] = {
        "issues": [],
        "pulls": [{"number": 9, "title": "b pr", "url": "https://x.test/p/9"}],
    }
    out = render_matrix("f", members, [pa, pb])
    # a second, standalone table with a repo column and a scroll box
    assert "activity-table" in out and "activity-scroll" in out
    assert ">repo</th>" in out and ">title</th>" in out
    # every open PR and issue across the fleet is listed, with its repo
    assert "#3" in out and "#9" in out and "a fix" in out and "b pr" in out
    assert "#7" in out and "a bug" in out
    assert ">a</a>" in out and ">b</a>" in out  # repo shown as a column value
    # PRs are grouped before issues
    assert out.index("#3") < out.index("#7")
    # header count summary
    assert "2 PRs · 1 issues" in out


def test_activity_table_empty_and_unreachable_are_tolerated():
    # no open items -> a single empty-state row, page still renders
    out = render_matrix("f", [M("o/a")], [payload("o/a", [row("license", "pass")])])
    assert "nothing open across the fleet" in out
    # an unreachable member contributes no rows but doesn't crash the table
    out2 = render_matrix("f", [M("o/a")], [None])
    assert "activity-table" in out2 and "nothing open across the fleet" in out2


def test_render_document_is_a_full_standalone_page():
    members = [M("o/a")]
    payloads = [payload("o/a", [row("license", "pass")])]
    doc = render_document("myfleet", members, payloads)
    assert doc.startswith("<!doctype html>")
    assert "<title>myfleet fleet</title>" in doc
    assert '<meta charset="utf-8">' in doc
    assert doc.rstrip().endswith("</html>")
    # the matrix body is embedded intact
    assert "license" in doc and "✓" in doc

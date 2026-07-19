from housekeeper.ci_versions import ci_versions


def test_action_refs_extracted():
    wf = "uses: zmaril/housekeeping@v0.21.0\nuses: zmaril/straitjacket@v0.2.3"
    assert ci_versions("zmaril/powdermonkey", wf) == {
        "housekeeping": "v0.21.0",
        "straitjacket": "v0.2.3",
    }


def test_install_script_tracked():
    wf = (
        "run: curl -fsSL https://raw.githubusercontent.com/zmaril/straitjacket/"
        "main/install.sh | sh\nuses: zmaril/housekeeping@v0.21.0"
    )
    v = ci_versions("zmaril/powderworks", wf)
    assert v == {"housekeeping": "v0.21.0", "straitjacket": "install.sh"}


def test_self_hosted_tools_report_self():
    # a repo that IS the tool runs it from source, not via a pinned ref.
    assert ci_versions("zmaril/housekeeping", "")["housekeeping"] == "self"
    assert ci_versions("zmaril/Straitjacket", "")["straitjacket"] == "self"


def test_missing_ref_is_empty():
    v = ci_versions("zmaril/entl", "uses: zmaril/straitjacket@main")
    assert v["housekeeping"] == ""  # entl doesn't run the housekeeping action
    assert v["straitjacket"] == "main"

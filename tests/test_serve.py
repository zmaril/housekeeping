from housekeeper.serve import _inject

DOC = (
    '<!doctype html>\n<html lang="en">\n<head>\n</head>\n'
    "<body>\nMATRIX_CONTENT\n</body>\n</html>\n"
)


def test_inject_adds_controls_after_body():
    out = _inject(DOC, "generated 2026-01-01T00:00:00+00:00")
    assert "hk-regen" in out and "Regenerate" in out  # the button is present
    assert "/regen" in out  # the POST endpoint the button hits
    assert "generated 2026-01-01T00:00:00+00:00" in out  # the status stamp
    # controls sit right after <body>, before the page content
    assert out.index("hk-regen") < out.index("MATRIX_CONTENT")


def test_inject_is_idempotent_on_body_and_escapes_status():
    out = _inject(DOC, "<danger>")
    assert out.count('id="hk-regen"') == 1  # injected exactly once
    assert "<danger>" not in out and "&lt;danger&gt;" in out  # status is escaped

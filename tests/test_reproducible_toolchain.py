from housekeeper.checks.reproducible_toolchain import reproducible_toolchain
from housekeeper.registry import Status


def write_wf(tmp_path, name, content):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


class Ctx:
    def __init__(self, tmp_path):
        self.workdir = tmp_path


def test_flags_node_version_latest(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        """\
name: CI
on: {push: {}}
jobs:
  test:
    steps:
      - uses: actions/setup-node@v4
        with: {node-version: latest}
""",
    )
    r = reproducible_toolchain(Ctx(tmp_path))
    assert r.status == Status.FAIL
    assert "node-version" in r.details


def test_flags_python_wildcard(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {push: {}}\n"
        "jobs:\n  t:\n    steps:\n"
        "      - uses: actions/setup-python@v5\n"
        "        with: {python-version: '*'}\n",
    )
    assert reproducible_toolchain(Ctx(tmp_path)).status == Status.FAIL


def test_flags_x_style_wildcard(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {push: {}}\n"
        "jobs:\n  t:\n    steps:\n"
        "      - uses: actions/setup-node@v4\n"
        "        with: {node-version: 18.x}\n",
    )
    assert reproducible_toolchain(Ctx(tmp_path)).status == Status.FAIL


def test_pinned_version_passes(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {push: {}}\n"
        "jobs:\n  t:\n    steps:\n"
        "      - uses: actions/setup-node@v4\n"
        "        with: {node-version: 20.11.0}\n",
    )
    assert reproducible_toolchain(Ctx(tmp_path)).status == Status.PASS


def test_go_stable_channel_is_allowed(tmp_path):
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {push: {}}\n"
        "jobs:\n  t:\n    steps:\n"
        "      - uses: actions/setup-go@v5\n"
        "        with: {go-version: stable}\n",
    )
    assert reproducible_toolchain(Ctx(tmp_path)).status == Status.PASS


def test_rust_toolchain_stable_ref_is_not_flagged(tmp_path):
    # dtolnay/rust-toolchain@stable pins the channel via the ref, no version key.
    write_wf(
        tmp_path,
        "ci.yml",
        "name: CI\non: {push: {}}\n"
        "jobs:\n  t:\n    steps:\n"
        "      - uses: dtolnay/rust-toolchain@stable\n",
    )
    assert reproducible_toolchain(Ctx(tmp_path)).status == Status.PASS

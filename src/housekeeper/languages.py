"""Every per-language / per-ecosystem fact, in one place.

Two related registries live here so language knowledge stops being scattered across
the checks:

- An **`Ecosystem`** is a package-manager world detected by its manifest file
  (cargo, bun, npm, uv, ruby, go, …). It carries everything a check needs to reason
  about that world: its lockfile and how to verify/regenerate it, its dependabot
  ecosystem id, its build-junk gitignore patterns, a CI job template, and a
  `PinRule` for telling a pinned version specifier from a floating one.
- A **`Language`** is the programming language an ecosystem is written in (rust, js,
  python, ruby, go) — the CI signals that prove it's tested, linted, and formatted.
  Several ecosystems share one language (bun/npm/pnpm/yarn are all `js`), which is
  why they're separate tables joined by `Ecosystem.language`.
- **`TypedLanguage`** is the orthogonal type-layer axis (typescript, python,
  clojure): detected by its own config files, not a manifest, and graded on whether
  a typechecker runs in CI.

A check that needs to know something language-specific reads it off these tables; it
never hard-codes "cargo" or a `cargo test` regex itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

# ---- CI job templates (used by the ci-exists fix) ----------------------------

CARGO_CI = """\
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with: {components: 'clippy, rustfmt'}
      - run: cargo fmt --check
      - run: cargo clippy -- -D warnings
      - run: cargo test
"""

BUN_CI = """\
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
      - run: bun install --frozen-lockfile
      - run: bun run lint
      - run: bun test
"""

UV_CI = """\
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
"""

RUBY_CI = """\
  ruby:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ruby/setup-ruby@v1
        with: {bundler-cache: true}
      - run: bundle exec rubocop
      - run: bundle exec rake test
"""

GO_CI = """\
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
      - run: gofmt -l . && test -z "$(gofmt -l .)"
      - run: go vet ./...
      - run: go test ./...
"""

# Full typecheck workflows (used by the typecheck fix), per JS runner.
BUN_TYPECHECK = """\
name: typecheck
on:
  push:
    branches: [main]
  pull_request:

jobs:
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
      - run: bun install --frozen-lockfile
      - run: bunx tsc --noEmit
"""

NPM_TYPECHECK = """\
name: typecheck
on:
  push:
    branches: [main]
  pull_request:

jobs:
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npx tsc --noEmit
"""


# ---- Languages: the test / lint / fmt signals per language -------------------


@dataclass(frozen=True)
class Language:
    """A programming language's CI fingerprint: the commands that prove it's
    exercised. Patterns match against concatenated workflow `run:`/`uses:` text."""

    name: str
    test: re.Pattern
    lint: re.Pattern
    fmt: re.Pattern


LANGUAGES: dict[str, Language] = {
    "rust": Language(
        "rust",
        test=re.compile(r"\bcargo (nextest|test)\b"),
        lint=re.compile(r"\bclippy\b"),
        fmt=re.compile(r"\b(cargo fmt|rustfmt)\b"),
    ),
    "js": Language(
        "js",
        test=re.compile(
            r"\b(bun test|npm test|pnpm test|yarn test|vitest|jest|playwright)\b"
        ),
        lint=re.compile(r"\b(eslint|oxlint|biome (check|lint|ci))\b"),
        fmt=re.compile(r"\b(prettier|dprint|biome (check|format|ci))\b"),
    ),
    "python": Language(
        "python",
        test=re.compile(r"\b(pytest|python -m unittest|tox)\b"),
        lint=re.compile(r"\b(ruff check|flake8|pylint)\b"),
        fmt=re.compile(r"\b(ruff format|black)\b"),
    ),
    "ruby": Language(
        "ruby",
        test=re.compile(r"\b(rspec|rake (test|spec)|minitest)\b"),
        lint=re.compile(r"\b(rubocop|standardrb)\b"),
        fmt=re.compile(r"\b(rubocop|standardrb)\b"),
    ),
    "go": Language(
        "go",
        test=re.compile(r"\bgo test\b"),
        lint=re.compile(r"\b(go vet|golangci-lint|staticcheck)\b"),
        fmt=re.compile(r"\b(gofmt|gofumpt)\b"),
    ),
}


# ---- Pin rules: how an ecosystem tells a pinned specifier from a floating one --

SHA40 = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class PinRule:
    """Per-ecosystem rule for judging a version specifier string.

    The pinned-versions check owns the *manifest-format parsing* — package.json
    (JSON), pyproject/Cargo (TOML), Gemfile (text), workflow YAML (`uses:`) differ
    structurally, so extracting name->specifier pairs is format-specific. A PinRule
    owns the *ecosystem-specific judgement* applied to each extracted specifier, so
    the check never hard-codes "an exact semver" or the `@stable` channel itself.

    `classify(spec)` maps one specifier string to:

    - ``"pinned"``   — a fully-pinned specifier (an exact version, or a 40-hex SHA).
    - ``"bounded"``  — a capped range (`>=1.7,<2.0`, `~> 7`): counted separately and
      accepted only when the check's `capped_ok` knob is set.
    - ``"channel"``  — a moving release channel that is allowed anyway (`@stable`).
    - ``"local"``    — a path/link/workspace dep, not a released version: excluded.
    - ``"floating"`` — anything else.

    `advisory` marks an ecosystem whose floating specifiers are advisory-only by
    default because its lockfile pins the actual build (cargo, via Cargo.lock)."""

    pinned: re.Pattern  # a fully-pinned specifier matches this end-to-end
    bounded: re.Pattern | None = None  # a capped range (counted; accepted if capped_ok)
    local_prefixes: tuple[str, ...] = ()  # spec prefixes for local/non-version deps
    channels: frozenset[str] = frozenset()  # allowed moving release channels
    sha: re.Pattern | None = None  # commit-SHA pin (git rev / action ref)
    advisory: bool = (
        False  # floating is advisory-only by default (a lockfile pins builds)
    )

    def classify(self, spec: str) -> str:
        spec = spec.strip()
        if self.local_prefixes and spec.startswith(self.local_prefixes):
            return "local"
        if spec in self.channels:
            return "channel"
        if self.pinned.fullmatch(spec):
            return "pinned"
        if self.bounded is not None and self.bounded.search(spec):
            return "bounded"
        return "floating"


# npm/bun: pinned is an exact semver (1.2.3, 1.0.0-beta.5); ^/~/ranges/tags float.
# file:/link:/workspace:/portal: and path (./, /) specifiers are local, not versions.
NPM_PINS = PinRule(
    pinned=re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?"),
    local_prefixes=("file:", "link:", "workspace:", "portal:", ".", "/"),
)
# python (PEP 508): pinned is a lone `==X.Y.Z` (no `*`, single clause); a range with
# both a lower and an upper bound is bounded; everything else floats.
PYTHON_PINS = PinRule(
    pinned=re.compile(r"===?\s*[^,*][^,*]*"),
    bounded=re.compile(r"(?=.*>)(?=.*<)"),
)
# ruby: an exact `= X.Y.Z` (or bare `X.Y`) is pinned; `~>` is bounded; comparisons float.
RUBY_PINS = PinRule(
    pinned=re.compile(r"=?\s*v?\d+(?:\.\d+)*"),
    bounded=re.compile(r"~>"),
)
# cargo: an exact `=X.Y.Z` version (or a git `rev` that is a 40-hex SHA) is pinned;
# advisory by default because Cargo.lock pins the build.
CARGO_PINS = PinRule(
    pinned=re.compile(r"=.*"),
    sha=SHA40,
    advisory=True,
)
# github-actions: pinned is a 40-hex commit SHA; @stable/@oldstable are allowed channels.
ACTIONS_PINS = PinRule(
    pinned=SHA40,
    channels=frozenset({"stable", "oldstable"}),
)


# ---- Ecosystems: a package-manager world detected by its manifest ------------


@dataclass(frozen=True)
class Ecosystem:
    """A package-manager world. The first fields are positional for backwards
    compatibility; the rest carry the per-ecosystem knowledge the checks need,
    including `recommends` — the recommended fleet setup for this ecosystem — and
    `pins`, how pinned-versions judges this ecosystem's specifiers."""

    name: str
    manifest: str
    lockfile: str | None
    dependabot: str  # package-ecosystem value dependabot expects
    dependabot_alts: tuple[str, ...] = ()  # also acceptable in dependabot.yml
    language: str = ""  # key into LANGUAGES ("" for github-actions)
    tool: str | None = None  # binary for lockfile ops
    lock_check: tuple[str, ...] = ()  # command to verify the lockfile is in sync
    lock_regen: tuple[str, ...] = ()  # command to regenerate it
    gitignore: tuple[str, ...] = ()  # build-junk patterns .gitignore should carry
    ci_template: str = ""  # CI job snippet the ci-exists fix scaffolds
    typecheck_template: str = ""  # full typecheck workflow the typecheck fix scaffolds
    pins: PinRule | None = (
        None  # how pinned-versions judges this ecosystem's specifiers
    )
    recommends: tuple[str, ...] = ()  # recommended fleet setup for this ecosystem


# ---- Recommended fleet setup per ecosystem (inspectable, not buried in a check) ----

_JS_RECOMMENDS = (
    "lockfile committed and in sync (lockfiles)",
    "lint + test in CI (ci-exists)",
    "tsc --noEmit typecheck in CI (typecheck)",
)


ECOSYSTEMS: dict[str, Ecosystem] = {
    "cargo": Ecosystem(
        "cargo",
        "Cargo.toml",
        "Cargo.lock",
        "cargo",
        language="rust",
        tool="cargo",
        lock_check=("cargo", "metadata", "--locked", "--format-version", "1"),
        lock_regen=("cargo", "metadata", "--format-version", "1"),
        gitignore=("target/",),
        ci_template=CARGO_CI,
        pins=CARGO_PINS,
        recommends=(
            "Cargo.lock committed and in sync (lockfiles)",
            "cargo fmt --check, clippy, and test in CI (ci-exists)",
            "straitjacket wired into CI (straitjacket)",
            "a pinned toolchain (reproducible-toolchain)",
        ),
    ),
    "bun": Ecosystem(
        "bun",
        "package.json",
        "bun.lock",
        "bun",
        ("npm",),
        language="js",
        tool="bun",
        lock_check=("bun", "install", "--frozen-lockfile", "--dry-run"),
        lock_regen=("bun", "install"),
        gitignore=("node_modules/",),
        ci_template=BUN_CI,
        typecheck_template=BUN_TYPECHECK,
        pins=NPM_PINS,
        recommends=_JS_RECOMMENDS,
    ),
    "pnpm": Ecosystem(
        "pnpm",
        "package.json",
        "pnpm-lock.yaml",
        "npm",
        language="js",
        tool="pnpm",
        lock_check=("pnpm", "install", "--frozen-lockfile", "--lockfile-only"),
        lock_regen=("pnpm", "install", "--lockfile-only"),
        gitignore=("node_modules/",),
        pins=NPM_PINS,
        recommends=_JS_RECOMMENDS,
    ),
    "yarn": Ecosystem(
        "yarn",
        "package.json",
        "yarn.lock",
        "npm",
        language="js",
        tool="yarn",
        lock_check=("yarn", "install", "--immutable", "--mode=skip-build"),
        lock_regen=("yarn", "install", "--mode=skip-build"),
        gitignore=("node_modules/",),
        pins=NPM_PINS,
        recommends=_JS_RECOMMENDS,
    ),
    "npm": Ecosystem(
        "npm",
        "package.json",
        "package-lock.json",
        "npm",
        language="js",
        tool="npm",
        lock_check=("npm", "ci", "--dry-run", "--ignore-scripts"),
        lock_regen=("npm", "install", "--package-lock-only"),
        gitignore=("node_modules/",),
        typecheck_template=NPM_TYPECHECK,
        pins=NPM_PINS,
        recommends=_JS_RECOMMENDS,
    ),
    "uv": Ecosystem(
        "uv",
        "pyproject.toml",
        "uv.lock",
        "uv",
        ("pip",),
        language="python",
        tool="uv",
        lock_check=("uv", "lock", "--check"),
        lock_regen=("uv", "lock"),
        gitignore=(".venv/", "__pycache__/"),
        ci_template=UV_CI,
        pins=PYTHON_PINS,
        recommends=(
            "uv.lock committed and in sync (lockfiles)",
            "ruff check, ruff format, and pytest in CI (ci-exists)",
            "mypy or pyright typecheck in CI (typecheck)",
        ),
    ),
    "pip": Ecosystem(
        "pip",
        "requirements.txt",
        None,
        "pip",
        language="python",
        gitignore=(".venv/", "__pycache__/"),
        pins=PYTHON_PINS,
        recommends=("pin dependencies; prefer uv for a real lockfile (lockfiles)",),
    ),
    "ruby": Ecosystem(
        "ruby",
        "Gemfile",
        "Gemfile.lock",
        "bundler",
        language="ruby",
        ci_template=RUBY_CI,
        pins=RUBY_PINS,
        recommends=(
            "Gemfile.lock committed (lockfiles)",
            "rubocop and rake test in CI (ci-exists)",
        ),
    ),
    "go": Ecosystem(
        "go",
        "go.mod",
        "go.sum",
        "gomod",
        language="go",
        tool="go",
        ci_template=GO_CI,
        # No pin rule: go.mod requires resolve to exact versions (MVS + go.sum), so
        # there is no floating-specifier concept for pinned-versions to judge.
        recommends=(
            "go.sum committed (lockfiles)",
            "gofmt, go vet, and go test in CI (ci-exists)",
        ),
    ),
    "github-actions": Ecosystem(
        "github-actions",
        ".github/workflows",
        None,
        "github-actions",
        pins=ACTIONS_PINS,
        recommends=(
            "github-actions covered by dependabot (dependabot)",
            "read-only default workflow token (workflow-permissions)",
        ),
    ),
}


def detect_ecosystems(workdir: Path) -> list[Ecosystem]:
    """Which ecosystems this repo uses, from its manifest/lockfile files. Returns the
    shared registry entries (immutable), so every check sees the same facts."""
    found: list[Ecosystem] = []

    if (workdir / "Cargo.toml").is_file():
        found.append(ECOSYSTEMS["cargo"])

    if (workdir / "package.json").is_file():
        if (workdir / "bun.lock").is_file() or (workdir / "bun.lockb").is_file():
            bun = ECOSYSTEMS["bun"]
            if not (workdir / "bun.lock").is_file():
                bun = replace(bun, lockfile="bun.lockb")
            found.append(bun)
        elif (workdir / "pnpm-lock.yaml").is_file():
            found.append(ECOSYSTEMS["pnpm"])
        elif (workdir / "yarn.lock").is_file():
            found.append(ECOSYSTEMS["yarn"])
        else:
            found.append(ECOSYSTEMS["npm"])

    if (workdir / "pyproject.toml").is_file():
        # No lock yet or a uv.lock present — either way assume uv, the house style.
        found.append(ECOSYSTEMS["uv"])
    elif (workdir / "requirements.txt").is_file():
        found.append(ECOSYSTEMS["pip"])

    if (workdir / "Gemfile").is_file():
        found.append(ECOSYSTEMS["ruby"])

    if (workdir / "go.mod").is_file():
        found.append(ECOSYSTEMS["go"])

    workflows = workdir / ".github" / "workflows"
    if workflows.is_dir() and any(workflows.glob("*.y*ml")):
        found.append(ECOSYSTEMS["github-actions"])

    return found


# ---- Build artifacts: what a repo PRODUCES that CI must actually build --------


@dataclass(frozen=True)
class Artifact:
    """A build output a repo produces: a native addon, a wheel, a gem, a desktop
    app, a site bundle, a binary. Detected from source manifests (build outputs
    aren't committed), and carrying the CI signal that proves the artifact is
    actually built, so a green run that never builds it is caught.

    `ci_signal` matches concatenated workflow `run:`/`uses:` text (with
    `bun run <script>` expanded one level, the way the CI checks already do).
    `heavy` marks an artifact whose full build is too slow for every PR and belongs
    on a scheduled workflow (a Tauri bundle); the per-PR gate is a lighter compile
    check.
    """

    name: str
    label: str
    ci_signal: re.Pattern
    heavy: bool = False
    guidance: str = ""


ARTIFACTS: dict[str, Artifact] = {
    "napi": Artifact(
        "napi",
        "Node native addon (napi-rs)",
        re.compile(r"napi build", re.I),
        guidance="build the addon in CI with `napi build` "
        "(often a `bun run build` that maps to it)",
    ),
    "wheel": Artifact(
        "wheel",
        "Python extension wheel (PyO3/maturin)",
        re.compile(r"\bmaturin\b", re.I),
        guidance="build the extension in CI with maturin (develop or build)",
    ),
    "gem": Artifact(
        "gem",
        "Ruby native gem (Magnus/rb-sys)",
        re.compile(r"\b(extconf\.rb|create_rust_makefile)\b", re.I),
        guidance="compile the extension in CI (ruby extconf.rb && make)",
    ),
    "tauri": Artifact(
        "tauri",
        "Tauri desktop app",
        re.compile(r"tauri build", re.I),
        heavy=True,
        guidance="full `tauri build` on a scheduled workflow, plus a per-PR "
        "compile check (cargo check on src-tauri)",
    ),
    "site": Artifact(
        "site",
        "web/site bundle",
        # the named site bundlers, plus a browser-targeted `bun build` (Bun's own
        # bundler) — but NOT `bun build --compile`, which is a standalone binary.
        re.compile(
            r"\b(next build|vite build|astro build|gatsby build"
            r"|bun build(?![^\n]*--compile)[^\n]*--target[= ]browser)\b",
            re.I,
        ),
        guidance="run the site build in CI so a broken bundle fails before deploy",
    ),
    "binary": Artifact(
        "binary",
        "compiled binary",
        re.compile(r"(cargo (build|install|test)|bun build --compile)", re.I),
        guidance="build or test the binary in CI (cargo build/test, or bun build --compile)",
    ),
}


_ARTIFACT_SKIP_DIRS = {
    "node_modules",
    "vendor",
    "target",
    "dist",
    "build",
    "__pycache__",
}


def _manifest_files(workdir: Path, filename: str):
    """Every `filename` under workdir, skipping hidden and vendored/build dirs
    (so a napi dep inside node_modules never counts as the repo's own artifact)."""
    for path in workdir.rglob(filename):
        rel = path.relative_to(workdir)
        if any(
            part.startswith(".") or part in _ARTIFACT_SKIP_DIRS
            for part in rel.parts[:-1]
        ):
            continue
        yield path


def detect_artifacts(workdir: Path) -> list[Artifact]:
    """Which build artifacts this repo produces, from its source manifests. Returns
    deduped shared registry entries (immutable), like detect_ecosystems."""
    found: set[str] = set()

    # napi + web bundle + bun-compiled binary all read package.json — one walk.
    for pkg in _manifest_files(workdir, "package.json"):
        text = pkg.read_text(errors="replace")
        if "@napi-rs/cli" in text or "napi build" in text:
            found.add("napi")
        try:
            scripts = json.loads(text).get("scripts", {})
        except (json.JSONDecodeError, AttributeError):
            continue
        if not isinstance(scripts, dict):
            continue
        # A web bundle can hide under any build-like script name (`build`,
        # `build:web`, `web:build`), the way the builds check already treats them.
        build_scripts = [
            str(v)
            for name, v in scripts.items()
            if name == "build" or name.startswith("build:") or name.endswith(":build")
        ]
        if any(ARTIFACTS["site"].ci_signal.search(s) for s in build_scripts):
            found.add("site")
        if any("bun build --compile" in str(v) for v in scripts.values()):
            found.add("binary")

    # PyO3/maturin wheel.
    for pyproject in _manifest_files(workdir, "pyproject.toml"):
        text = pyproject.read_text(errors="replace")
        if 'build-backend = "maturin"' in text or "[tool.maturin]" in text:
            found.add("wheel")

    # Magnus/rb-sys gem native extension.
    for extconf in _manifest_files(workdir, "extconf.rb"):
        text = extconf.read_text(errors="replace")
        if "create_rust_makefile" in text or "rb_sys" in text:
            found.add("gem")

    # Tauri desktop app: a src-tauri/ dir with its config.
    for conf in _manifest_files(workdir, "tauri.conf.json"):
        if conf.parent.name == "src-tauri":
            found.add("tauri")

    # Compiled binary (Rust): a crate with [[bin]] or a main.rs / src/bin/.
    for cargo in _manifest_files(workdir, "Cargo.toml"):
        crate = cargo.parent
        if (
            "[[bin]]" in cargo.read_text(errors="replace")
            or (crate / "src" / "main.rs").is_file()
            or (crate / "src" / "bin").is_dir()
        ):
            found.add("binary")

    return [art for name, art in ARTIFACTS.items() if name in found]


# ---- Typed languages: the optional type-layer axis ---------------------------


@dataclass(frozen=True)
class TypedLanguage:
    """An optionally-typed language: present when one of its `markers` exists, and
    graded on whether `signal` (a typechecker) runs in CI."""

    name: str
    markers: tuple[str, ...]
    signal: re.Pattern
    guidance: str


TYPED_LANGUAGES: dict[str, TypedLanguage] = {
    "typescript": TypedLanguage(
        "typescript",
        ("tsconfig.json", "jsconfig.json"),
        re.compile(r"\b(tsc|vue-tsc|tsgo|typecheck|astro check)\b"),
        "run tsc (or vue-tsc / astro check) in CI",
    ),
    "python": TypedLanguage(
        "python",
        ("pyproject.toml", "requirements.txt"),
        re.compile(r"\b(mypy|pyright|basedpyright|pyre|pytype|pyrefly|ty check)\b"),
        "run mypy / pyright / ty in CI",
    ),
    "clojure": TypedLanguage(
        "clojure",
        ("deps.edn", "project.clj"),
        re.compile(r"\b(clj-kondo|core\.typed|typedclojure)\b"),
        "run clj-kondo (or core.typed) in CI",
    ),
}


def detect_typed_languages(workdir: Path) -> list[str]:
    """Typed-language layers present by their marker files (see TYPED_LANGUAGES).
    Pure detection — the typecheck check adds its own verdict logic on top."""
    return [
        name
        for name, tl in TYPED_LANGUAGES.items()
        if any((workdir / marker).is_file() for marker in tl.markers)
    ]

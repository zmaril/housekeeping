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
    """A package-manager world. The first four fields are positional for backwards
    compatibility; the rest carry the per-ecosystem knowledge the checks need."""

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
    ),
    "pip": Ecosystem(
        "pip",
        "requirements.txt",
        None,
        "pip",
        language="python",
        gitignore=(".venv/", "__pycache__/"),
        pins=PYTHON_PINS,
    ),
    "ruby": Ecosystem(
        "ruby",
        "Gemfile",
        "Gemfile.lock",
        "bundler",
        language="ruby",
        ci_template=RUBY_CI,
        pins=RUBY_PINS,
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
    ),
    "github-actions": Ecosystem(
        "github-actions",
        ".github/workflows",
        None,
        "github-actions",
        pins=ACTIONS_PINS,
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

"""Every per-language / per-ecosystem fact, in one place.

Two related registries live here so language knowledge stops being scattered across
the checks:

- An **`Ecosystem`** is a package-manager world detected by its manifest file
  (cargo, bun, npm, uv, ruby, go, …). It carries everything a check needs to reason
  about that world: its lockfile and how to verify/regenerate it, its dependabot
  ecosystem id, its build-junk gitignore patterns, and a CI job template.
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


# ---- Ecosystems: a package-manager world detected by its manifest ------------


@dataclass(frozen=True)
class Ecosystem:
    """A package-manager world. The first five fields are positional for backwards
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
    ),
    "pip": Ecosystem(
        "pip",
        "requirements.txt",
        None,
        "pip",
        language="python",
        gitignore=(".venv/", "__pycache__/"),
    ),
    "ruby": Ecosystem(
        "ruby",
        "Gemfile",
        "Gemfile.lock",
        "bundler",
        language="ruby",
        ci_template=RUBY_CI,
    ),
    "go": Ecosystem(
        "go",
        "go.mod",
        "go.sum",
        "gomod",
        language="go",
        tool="go",
        ci_template=GO_CI,
    ),
    "github-actions": Ecosystem(
        "github-actions",
        ".github/workflows",
        None,
        "github-actions",
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

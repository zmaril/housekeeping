# Changelog

Notable changes to housekeeping, newest first.

## v0.26.0 — 2026-07-18

- `lockfiles` gains a git-history staleness fallback for ecosystems with no
  native sync check (ruby's Gemfile.lock, go's go.sum). Where cargo/uv/bun/npm
  are verified with their own tool, ruby and go were previously only noted as
  unverified; now the check compares commit timestamps and flags a lockfile
  whose manifest was committed in a strictly later commit as likely stale. The
  "not committed" branch also now distinguishes a gitignored lockfile, and a
  native-check ecosystem whose tool is absent falls back to the heuristic
  instead of going unverified. **Verdict change**: lockfiles can now fail
  ruby/go repos that carry a stale-by-history lockfile, so a repo that
  previously passed on presence alone may now fail.

## v0.24.0 — 2026-07-18

- New **recommended** `artifacts-built` check: for every build artifact
  detection finds a repo produces (napi addon, PyO3/maturin wheel, Magnus/rb-sys
  gem, Tauri app, web/site bundle, compiled binary), it greps the workflows for
  the build step that artifact needs and reports the ones with no build
  coverage. A heavy artifact (a Tauri bundle) is expected to build on a scheduled
  workflow; the lighter per-PR gate stays the required `builds` check's job. It
  is conservative — it matches workflow step/run text and resolves
  `bun`/`npm`/`pnpm`/`yarn run <name>` against the scripts of every package.json
  in the repo (nested included, so a `bun run build` that maps to `napi build` in
  a sub-package resolves), but it never runs anything. Because static parsing is
  imperfect it **warns rather than gates**. New check plus a new Action verdict:
  an Action-behavior change, so it needs a release bump (Zack cuts releases).

## 2026-07-18

- New `housekeeper new <name> --flavor rust|bun|python` command: scaffolds a
  fleet-compliant repo skeleton — CI/housekeeping workflows, committed git
  hooks, a `.housekeeping.toml` carrying the fleet declaration, LICENSE,
  `scripts/dev.sh`, dependabot config, CODEOWNERS, and `notes/design.md` — then
  prints what it created and the human next steps it can't do itself: creating
  the repo on GitHub, turning on branch protection, running `dev.sh` once to
  generate the lockfile, and letting the captain sync the managed lint configs.
  A CLI command only: no check verdicts and no `@v1` Action behavior change.
- New `housekeeper detect` command: prints the repo's detected ecosystems,
  typed-language layers, and the build artifacts it produces, plus the
  recommended fleet setup per ecosystem (`--json` for machine output). Backed by
  a new artifact-detection layer in `languages.py` (`Artifact` / `ARTIFACTS` /
  `detect_artifacts`) that reads source manifests — napi addons, PyO3/maturin
  wheels, Magnus/rb-sys gems, Tauri apps, web/site bundles, and compiled
  binaries — skipping vendored and build trees so a dependency's artifact never
  counts as the repo's own. `Ecosystem` gains a `recommends` field carrying the
  recommended setup for that world. Detection-only: no check verdicts change.

## v0.25.0 — 2026-07-18

- New **`pinned-versions`** check (recommended, check-only): flags floating
  version specifiers per detected ecosystem so a dependency can't silently drift
  — the failure mode that shipped fluessig's floating `@typespec/compiler
  ^1.13.0` as a fleet-wide codegen change with no diff to point at. It leans on
  the existing ecosystem detection (`ctx.ecosystems`) and grades each world by
  its own idea of "pinned": **npm/bun** (`dependencies` + `devDependencies` of
  every package.json) wants an exact semver; **python** (`pyproject.toml` +
  `requirements.txt`, PEP 508) wants a lone `==X.Y.Z`; **ruby** (`Gemfile`,
  `*.gemspec`) wants `= X.Y.Z`; **actions** (`uses:` across workflows and
  `.github/actions/**/action.yml`) want a **40-char commit SHA** — and
  `@stable`/`@oldstable` release channels are allowed, aligned with
  `reproducible-toolchain`. **cargo** is **advisory by default** because
  `Cargo.lock` pins the build (reported in the note, not counted). Local / path /
  workspace / SHA-pinned deps are never flagged, and peerDependencies + bounded
  ranges are counted in the note rather than failed. Configure scope with
  `[pinned-versions]`: `cargo = "advisory" | "on" | "off"`, `actions = true |
  false`, `capped_ok` (accept bounded ranges / `~>`), and `ignore` (names to
  skip). No auto-fix — pinning to a version is a human decision (like `builds` /
  `reproducible-toolchain`), and dependabot still bumps the pins afterwards. New
  check, so this needs a release bump (Zack cuts releases).
## v0.21.0 — 2026-07-18

- New **`allow-auto-merge`** check (recommended, fixable): asserts the repo's
  GitHub `allow_auto_merge` setting matches a declared preference. The default
  preference is **off** — this fleet's workflow is branch-protection +
  required-checks + a human doing the merge, and auto-merge fires the merge with
  nobody at the merge moment. A repo that wants auto-merge opts in with
  `[allow-auto-merge] enabled = true` in `.housekeeping.toml`; the check then
  passes only when GitHub's actual setting matches, either way. Auto-merge never
  bypasses branch protection or required checks, so on is a legitimate choice —
  this is a preference, not a hardcoded polarity. `housekeeper fix
  allow-auto-merge` PATCHes the setting to match (needs an admin token; a 403
  prints how to flip it by hand). New check, so this needs a release bump (Zack
  cuts releases).

## v0.20.0 — 2026-07-09

- New **`coverage`** check (recommended, advisory): every detected language
  ecosystem (rust, js, python) must have *some* coverage tool wired up —
  presence-only, not a percentage or threshold. It accepts a range of signals so
  each repo configures as it likes: a coverage config file (`codecov.yml`,
  `.coveragerc`), a CI step or task-runner target (`cargo llvm-cov`, `tarpaulin`,
  `grcov`, `bun test --coverage`, `c8`/`nyc`, `pytest-cov`), or a manifest
  dependency. Skips when no rust/js/python ecosystem is present. Advisory
  (`recommended`) by default following the `ci-green` advisory-first precedent, so
  it warns rather than gating while repos wire coverage; promote per-repo to
  `required` via `powderworks/housecaptain.toml [policy] locked` later. No patch /
  changed-lines coverage — that machinery doesn't exist yet. See the design note
  `notes/fleet-policy-test-layout-and-coverage.md`.

## v0.19.0 — 2026-07-08

- **Per-repo `only` targeting** for `[[policy.managed-config]]`: an optional
  `only = ["owner/repo", …]` allow-list restricts a fleet-owned config to just
  the members that actually use it, instead of syncing byte-identically to
  every in-scope member. Empty `only` (the default) keeps today's
  apply-to-every-in-scope-member behavior; a non-empty list scopes both the
  sync and the drift notes to the listed repos, emitting a `skipped (not in
  only list)` row for the rest. Values must match `[[member]].repo` exactly,
  and unknown repos are tolerated — a listed repo that isn't a member simply
  never matches. Lets a config like biome, used by only a subset of the fleet,
  target precisely.

## v0.18.0 — 2026-07-08

- **PR-context grading**: `ci-green`, `branch-protection`, and
  `required-checks` grade the default branch's runs or the repo's settings —
  nothing a pull request's diff can change — so on `pull_request` events they
  now demote from required to recommended (warn, with an explanatory note in
  the table). Push, schedule, and local runs keep them hard, which is where
  main's state is actionable; the captain's fleet table still catches a
  rotting main. Ends the admin-merge treadmill: the bootstrap compliance PR,
  the fix-for-the-red-main PR, and every innocent PR under a nightly flake
  all merge on their own merits.
- New **`ruleset-bypass`** check (recommended, fixable): a gating ruleset
  (pull_request / required_status_checks rules) must name a bypass actor,
  because GitHub rulesets ignore `gh pr merge --admin` without one.
  `housekeeper fix ruleset-bypass` grants Repository admin
  (`bypass_mode: always`).
- Hardening: git exports `GIT_DIR`/`GIT_INDEX_FILE` to hooks, which silently
  redirected the test suite's temp-repo git calls at the real repo when run
  under pre-commit (staging the repo's deletion into the live index, once).
  The hook now unsets them and an autouse conftest fixture strips them for
  every test.

## v0.17.0 — 2026-07-08

- `scripts` check (required): shell scripts live under `scripts/`, a
  `scripts/dev.sh` stands up the basic dev environment, and the README points at
  it. Hidden and vendored trees (`.githooks/`, `node_modules/`, …) are never
  scanned — git hooks belong in `.githooks/`. Configurable via `[scripts]`
  (`dir`, `dev`, `allow`). Housekeeping now ships its own `scripts/dev.sh`.
- Fleet dashboard now carries a second table: **every open PR and issue across
  the fleet**, one row each, with the repo as a column (PRs first, then issues,
  each linking to GitHub) and a per-fleet count. Open issues/PRs are folded into
  the audit payload (`fetch_activity`), so the dashboard stays a pure view.
- New `housekeeper serve housecaptain.toml` command: serves the dashboard from a
  local web server with a **Regenerate** button — and an optional 60s
  auto-refresh — that re-audits the fleet on demand. The static `--html` file
  output is untouched; the live controls are injected only into the served page.
- `housekeeper fleet` now audits members **concurrently** (a thread pool,
  results still in fleet order), so a full re-audit drops to about the slowest
  single repo instead of the sum — roughly 3× faster on the powderworks fleet.
- Dashboard legend spells out the glyphs — `warn` is now
  "recommended, not required" and `fail` is "required", with hover tooltips —
  so a `!` cell reads as advisory rather than mysterious.

## v0.16.0 — 2026-07-05

- Fleet dashboard now shows **which shared-CI ref each repo pins** — two version
  rows (`housekeeping CI`, `straitjacket CI`) above the check matrix, read from
  each member's cloned workflows (`zmaril/…@REF`, an `install.sh` line, or `self`
  when the repo is the tool). Surfaces fleet drift at a glance: who's on an old
  pin, who floats on `main`. Extracted in the new `ci_versions` module and folded
  into the audit payload.
- Dashboard repeats the repo logo/name headers in a `<tfoot>`, framing the matrix
  top and bottom.

## v0.15.0 — 2026-07-05

- `stylelint` check (recommended): if a repo has stylesheets (`.css`/`.scss`/
  `.less`) or an existing stylelint config, a config must be present and
  stylelint must run in CI; skips when there's no CSS to lint. Fixable:
  scaffolds `.stylelintrc.json` + a workflow.
- `vale` check (recommended): a `.vale.ini` (with a resolvable `StylesPath`) is
  present and vale runs in CI. Overlaps with `straitjacket` by design —
  straitjacket scans for slop, vale enforces house style and terminology.
  Fixable: scaffolds `.vale.ini` + `styles/` + a workflow.
- `codespell` check (recommended): codespell runs in CI. Split from vale on
  purpose — vale's dictionary spell-check false-positives on every unknown
  jargon word, so vale is left to style/terminology and codespell does
  spelling. codespell flags only *known* misspellings, so it can't cry wolf on
  a term it's never seen while still catching real typos. Fixable: scaffolds
  `.codespellrc` + a workflow.
- Managed configs: the fleet captain can now **own** a check's config and push
  it outward. `[[policy.managed-config]]` entries in `housecaptain.toml` point
  a member destination at a canonical source under `.fleet/` in the captain
  repo. `housekeeper captain --sync-configs` (action input `sync-configs`)
  opens an isolated, config-only PR on each member whose copy has drifted —
  branch `housekeeping/fleet-config-<check>`, reused idempotently. Distribution
  is deliberately *not* a fix: the captain ships the artifact for the member to
  adopt at their own pace and never touches member code. Drift is surfaced on
  the captain report as an informational note, never a member-CI failure. Pair
  with an `on.push` path filter for `.fleet/**` so a config change fans out on
  merge.
- `stray-todos` fix: tighten the marker match so it no longer flags an enum/object
  key named `Todo:` or the word "todo" used mid-sentence in prose. A marker must sit
  right after a comment leader, be a heading, or be the first token on a line. Found
  the day it shipped, when the freshly-enforced check fired on powdermonkey's
  `PhaseStatus` enum.

## v0.14.0 — 2026-07-05

- `stray-todos` check (recommended): the `TODO` / `TBD` / `FIXME` / `WIP` markers
  belong in one todo file (the same pile `stray-files` points at, default
  `todo.txt`), not scattered through comments and docs where nobody tracks them. It
  flags the marker *form* — the tag with a trailing colon or paren, or a heading
  that opens with it — in either case, over git-tracked files only; the word "todo"
  used in prose is left alone. Deliberate keepers via `[stray-todos] ignore = [...]`.
  Enforced as required across the powderworks fleet.

## v0.13.0 — 2026-07-04

- **Re-baselined to 0.x.** Housekeeping had jumped to `v1.x` while it's still
  young and evolving fast; nothing external depends on it, so the versions are
  remapped `v1.N → v0.N` (this release was `v1.13.0`) and the published `v1.x`
  releases and the moving `v1` tag are retired. Straitjacket (0.2.x) is the
  sibling model — pre-1.0 until the check set settles.
- Docs: the recommended action usage now pins the **full version**
  (`zmaril/housekeeping@v0.9.0`) instead of the moving `@v0` tag. Housekeeping
  adds checks in minor releases, and a floating major tag applies them to a
  consumer's repo the moment they ship — a required check they never opted into,
  turning an unrelated PR red. Pinning means new checks arrive only on a
  deliberate bump. Same reasoning as the `reproducible-toolchain` check, applied
  to our own action.
- Dogfood: the self-audit's straitjacket step now uses the pinned
  `zmaril/straitjacket@v0.2.3` action instead of installing from `main`, so a new
  straitjacket rule can't fail this repo's CI until we choose to bump.

## v0.11.0 — 2026-07-04

- Internal: per-language / per-ecosystem knowledge is now consolidated in one
  module, `languages.py`. Previously "cargo" (and every other ecosystem) was
  defined across five files — `Ecosystem` detection in `context.py`, CI signals
  and templates in `ci.py`, lockfile commands in `lockfiles.py`, gitignore
  patterns in `gitignore.py`, typecheck signals in `typecheck.py`. They're now
  fields on typed `Ecosystem` / `Language` / `TypedLanguage` records in a single
  registry; a check reads `eco.gitignore` or `LANGUAGES[eco.language].test`
  instead of carrying its own table. Pure refactor — no behaviour change, same
  148 tests. Adding a language is now one registry entry.

## v0.10.0 — 2026-07-04

- `ci-scheduled-run` check (recommended): CI should run on a schedule, not only on
  push/PR. Push-only CI never exercises the repo between commits, so bitrot — an
  expiring token, a moved dependency, a yanked pinned action — sits invisible until
  the next contributor's PR trips over it. Passes when any workflow has a
  `schedule:` trigger. Grounded in Dan Luu's *broken-builds* / *why-benchmark*.
- `ci-job-timeout` check (recommended): push/PR CI jobs should set `timeout-minutes`.
  GitHub's default is 6 hours, so a hung job burns runner minutes and shows a lying
  "in progress" until the ceiling — and blocks the merge on a required check the
  whole time. Reusable-workflow job calls (which can't set the key) are skipped.
- `test-retry-masking` check (recommended): auto-rerunning tests until they pass
  launders flakiness into a false green. Flags `pytest --reruns`, `jest --retries`,
  Playwright/vitest/nextest nonzero retries in CI commands and the usual config
  files. Retries have legitimate uses, so except it where deliberate. The mirror of
  `ci-continue-on-error`; grounded in Dan Luu's *wat*.

## v0.9.0 — 2026-07-04

- `ci-continue-on-error` check (required): a test/lint/build step must not be
  allowed to fail silently. `continue-on-error: true` lets a step (or a whole job)
  fail while the workflow still reports success — on a step that runs the tests,
  the linter, or the build, CI goes green while the thing it exists to catch is
  red. Flagged on any job marked `continue-on-error`, and on steps whose command is
  an unambiguous test/lint/build invocation; a genuinely tolerable step is excepted
  via `.housekeeping.toml`. Grounded in Dan Luu's *broken-builds*.
- `reproducible-toolchain` check (required): CI must not build on a floating
  toolchain version. `node-version: latest`, `python-version: '*'`, an `x`-style
  wildcard on a `setup-*` step means the same commit builds differently tomorrow —
  silent bitrot when the upstream default moves. Bounded channels (Go's `stable`,
  `dtolnay/rust-toolchain@stable`) are intentionally allowed. Grounded in Dan Luu's
  *everything-is-broken* (reproducibility).
- `codeowners` check (recommended): a non-empty CODEOWNERS routes review to whoever
  knows the code. Checks the three GitHub-honoured locations for at least one real
  ownership rule; softens to recommended since it's ceremony on a solo repo.
  Fixable: scaffolds `.github/CODEOWNERS` with a catch-all owner.

## v0.8.0 — 2026-07-04

- Fleet check-matrix dashboard: `housekeeper fleet --html FILE` writes a
  self-contained, theme-aware HTML page — a matrix of every fleet repo (rows)
  against every check (columns), each cell coloured by outcome (pass / warn /
  fail / skip / off) so the whole fleet's health reads at a glance. Recommended
  failures render as a warn, required failures as a hard fail; unreachable
  members collapse to a single "unreachable" row.
- Repos can declare an optional `logo = "..."` in `.housekeeping.toml` (an image
  URL or a repo-relative path, resolved to its raw URL) shown beside the repo
  name in the dashboard. The key is allow-listed, so it isn't reported as unknown
  config.

## v0.7.0 — 2026-07-04

- `required-checks` check (required): the default branch must actually *require*
  every status check that runs on a PR — not just require PRs. Branch protection
  can require a PR yet require no status checks, so a red CI run doesn't block the
  merge and the gate is theatre. Reads the ruleset's (and classic protection's)
  required contexts and compares them to the check-run names the repo's own PR
  workflows post; a check that runs but isn't required fails. Fan-out helper jobs
  (a paths-filter `changes` job, which carries `outputs:`) aren't counted. Fixable:
  writes the required set into the default-branch ruleset.
- `ci-scoped` check (recommended): heavy CI jobs shouldn't run on every PR
  regardless of what changed. A job that apt-installs system libraries or runs a
  native compiler (cargo/go/docker/xcode) on `pull_request` without scoping — a
  workflow `paths:` filter, a job `if:`, or a `needs:` on a fan-out job — is
  flagged. Once checks are required, an unscoped compile is minutes you can't merge
  past; a job-level `if:` keeps it a *skipped* (green) required check on unrelated
  PRs, so scoping stays required-check-safe.

## v0.6.0 — 2026-07-04

- Multi-language CI coverage: `ci-exists` now demands test, lint, AND fmt
  signals per detected language (rust, js, python, ruby, go) — a repo whose
  CI only exercises one of its languages fails with named gaps. Combined
  tools (biome, rubocop) satisfy lint+fmt for their language.
- Ruby joins ecosystem detection: Gemfile/Gemfile.lock, bundler dependabot
  coverage, rubocop/rspec signals, lockfile presence checked.
- `builds` check (required): every build target must actually run in CI —
  package.json `build*` scripts per PR (transitive script resolution), and
  tauri needs a per-PR compile check plus a scheduled full build. Born from
  a repo whose broken build:web sailed through green merges.
- `codegen-drift` check (required, config-declared): `[[codegen]]` entries
  in .housekeeping.toml name regen commands; CI must run each and assert
  zero diff afterward, so committed bindgen output can't drift.
- Dogfood: housekeeping's own CI gained `ruff format --check` and the
  codebase is now ruff-formatted.

## v0.5.0 — 2026-07-04

- Policy locks: `[policy] locked = [...]` (plus a top-level `captain =
  "owner/repo"`) in housecaptain.toml makes fleet policy law instead of
  expectation for those keys. Members declare `fleet = "owner/repo"` in
  .housekeeping.toml; their own audits then fetch the manifest, apply locked
  severities, and fail any PR that sets a locked key — so an agent can't add
  a stray file and except itself in the same diff. The captain backstops the
  last escape (deleting the fleet line is a surfaced conflict).

## v0.4.0 — 2026-07-04

- Captain dispatch: `housekeeper captain --dispatch` (action input
  `dispatch: true`) triggers every member's self-audit immediately — new
  checks reach the fleet when you push the button, not a week of crons
  later. Members' housekeeping workflows must carry the workflow_dispatch
  trigger, which the captain now requires.
- Unknown `[policy.*]` keys in housecaptain.toml are surfaced and fail the
  captain — a typo, or policy from a newer housekeeping than the captain
  running it; silence was against the house ethos either way.
- Same at member scale: unknown keys in `.housekeeping.toml` (a typo'd
  section, a `checks.webiste`) fail the audit with a `config` row instead
  of silently doing nothing.

## v0.3.0 — 2026-07-04

- `stray-files` grew a location policy: one todo pile (default `todo.txt`),
  notes corralled in one directory (default `notes/`), everything
  configurable — strays now get a destination, not just an accusation, and
  a second todo pile is called what it is.
- Fleet captains can require files: `[[policy.required-file]]` with `path`
  and `scope` (all/public/private) in housecaptain.toml — e.g. every open
  source member must carry `notes/design.md`.
- Our own design doc practices what the fleet now preaches: DESIGN.md moved
  to notes/design.md.

## 2026-07-04

- todo.txt retired: the fleet ledger is housecaptain.toml in
  zmaril/powderworks now (parked members carry their reasons on the roster).

## v0.2.2 — 2026-07-04

- `ci-green` never grades housekeeping-family workflows (self-audit,
  captain): on a flagship carrying both, each graded the other and one red
  deadlocked the pair — red because the other was red, forever. The family
  audits the repo; ci-green grades the repo's own CI.

## v0.2.1 — 2026-07-04

- The captain no longer mistakes a member's captain workflow for its
  self-audit (both use the action; found on the flagship itself, where
  housecaptain.yml sorts before housekeeping.yml).

## v0.2.0 — 2026-07-04

- Fleet captain: `housecaptain.toml` names a fleet; `housekeeper captain`
  (API-only, also the action's `captain:` input) checks every member is
  auditing itself — workflow present, triggers complete, latest run green —
  and surfaces fleet-policy vs member-config conflicts instead of silently
  resolving them. `housekeeper fleet` runs the full audit across all
  members locally with a scoreboard.
- `typecheck` check (required): if the language supports typechecking, it
  must run in CI — TypeScript (tsc and kin), Python (mypy/pyright/ty),
  Clojure (clj-kondo/core.typed); untyped JavaScript fails with guidance to
  add a type layer. Found live when 82 type errors had piled up invisibly in
  a repo whose CI linted and tested but never typechecked. The TS fix adds a
  typecheck workflow and preflights the current error count. Eating it
  ourselves: housekeeping now runs mypy in CI, and mypy's first pass caught
  a real crash path in the action-badge fix.
- `conventional-commits` check (recommended; required on this repo): enforced
  in CI and documented, with recent-adherence as a note — history is never
  judged retroactively. The fix sets squash merges to title from the PR
  title and adds a dependency-free PR-title workflow, so future main history
  is conventional by construction.
- This repo now enforces conventional PR titles on itself. Entries are dated; releases
that matter to Action consumers also get a version, because `uses:` resolves
tags — `v1` moves with compatible releases, `vX.Y.Z` tags are immutable. For
the CLI, plugin, and skill, the git SHA remains the real version.

## v0.1.0 — 2026-07-04

- `ci-exists` resolves `bun/npm/pnpm/yarn run <script>` through package.json
  scripts before pattern-matching, so a linter hidden behind `bun run check`
  counts (found live on powdermonkey — its first Action run failed on the
  false negative because `v1` predated the fix; this release ships it).
- `stray-files` check (recommended): no scratch `.md`/`.txt` piling up at the
  repo root; conventional community files and `[stray-files] allow` excepted.
- `stale` now checks `delete_branch_on_merge` and gained a fix: enable the
  setting and sweep already-merged branches, confirm-first.
- The tidy-up skill knows about powderworks cross-promotion on zmaril repos.

- `action-badge` check (recommended): a public repo that publishes an action
  should link its Marketplace listing in the README; the fix derives the
  slug from the action's name and inserts the badge under the title.
- housekeeping's own README carries its Marketplace badge.

## v0.0.1 — 2026-07-03

- Marketplace-valid action metadata: display name "Powderworks Housekeeping"
  (bare "housekeeping" collides with an existing name), description under
  125 characters. The `uses: zmaril/housekeeping@v0` path is unchanged.

## v0.0.0 — 2026-07-03

- GitHub Action: `uses: zmaril/housekeeping@v0` runs the audit in any
  repo's CI with results in the job summary. Admin-only settings the
  workflow token can't read skip with a note instead of guessing, and
  `ci-green` excludes the workflow it runs inside (a transient red would
  otherwise deadlock itself red forever). This repo runs it on itself,
  weekly and on every push/PR.
- The plugin marketplace is named `powderworks` — the family of Zack's open
  source tools — so the install is `/plugin install housekeeping@powderworks`.
- `changelog` check: a CHANGELOG file is now part of the floor (softer on
  private repos).
- Public vs. private profiles: private repos soften the audience-facing
  checks — website, license, changelog, README polish — and drop repo
  metadata nagging entirely. Engineering hygiene stays required everywhere.
- `readme` check requires actual `License` and `Contributing` section
  headings (word families count); a stray "license" in prose no longer
  satisfies the floor.
- Skills merged into one `tidy-up` skill; installable as a Claude Code
  plugin (`/housekeeping:tidy-up`) or via `npx skills add zmaril/housekeeping`.
- New checks: `secret-scanning`, `workflow-permissions`, `gitignore`.
- `ci-green` grades every repo workflow's latest completed default-branch
  run, not the latest run overall (which could be one of GitHub's internal
  dynamic workflows).
- Initial release: fifteen checks, confirm-first fixes, `check`/`fix`/`report`
  CLI, plus the `tidy-up` agent skill.

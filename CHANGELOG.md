# Changelog

Notable changes to housekeeping, newest first.

## v1.2.1 — 2026-07-04

- The captain no longer mistakes a member's captain workflow for its
  self-audit (both use the action; found on the flagship itself, where
  housecaptain.yml sorts before housekeeping.yml).

## v1.2.0 — 2026-07-04

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

## v1.1.0 — 2026-07-04

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

## v1.0.1 — 2026-07-03

- Marketplace-valid action metadata: display name "Powderworks Housekeeping"
  (bare "housekeeping" collides with an existing name), description under
  125 characters. The `uses: zmaril/housekeeping@v1` path is unchanged.

## v1.0.0 — 2026-07-03

- GitHub Action: `uses: zmaril/housekeeping@v1` runs the audit in any
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

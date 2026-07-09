# Fleet policy — test layout & coverage (exploration)

This is a design note, not an implementation. It works through **two policies the
fleet is *considering*** — where Rust tests live, and whether the fleet should
mandate code coverage — grounds each in measured numbers from the powderworks
repos, and lands a recommendation for each. Nothing here is being built yet; the
note **ends by asking which pieces to build.** No check code is added or changed.

The fleet under discussion is powderworks' members: `disponent`, `entl`,
`fluessig`, `straitjacket` (Rust), and `housekeeping` itself (Python — out of
scope for the Rust test-layout question). Measurements were taken on the checked-out
`main` of each on 2026-07-09.

## Grounding — how a housekeeper check actually works

Before proposing anything, the vocabulary, so the proposals below are concrete and
correct against the code as it stands (v0.19.0).

- **A check is a Python module** under `src/housekeeper/checks/`. It registers by
  decorating a `(ctx: RepoContext) -> Result` function with
  `@check("name", needs=(...))` (`registry.py:54`), imported once in
  `checks/__init__.py` so the decorator fires. `needs` is any of `"clone"` /
  `"api"` / `"admin"`; a check that walks the working tree declares `needs=("clone",)`
  and reads `ctx.workdir` (`context.py:92`). Its own config section comes from
  `ctx.config.section("<check-name>")`.
- **Status is `PASS | FAIL | SKIP | ERROR`** — that is the whole `Status` enum
  (`registry.py:13`). **There is no `WARN`.** What reads as "warn" in the output is
  purely a *rendering* of `status=fail` **and** `severity=recommended`
  (`cli.py:451` terminal, `cli.py:475` markdown → `"! warn"`).
- **Severity is orthogonal to status** and lives in config, not in the check:
  `SEVERITIES = ("required", "recommended", "off")` (`config.py:9`), defaulted per
  check in `DEFAULT_SEVERITY` (`config.py:11`), unknown checks defaulting to
  `"required"` (`config.py:83`). **Only `required` gates the exit code**: the run
  fails (exit 1) iff some row is `status in ("fail","error")` **and**
  `severity == "required"` (`cli.py:485`). A `recommended` failure is advisory — it
  warns, it never fails CI. An `off` check is skipped entirely (`cli.py:137`).
- **The advisory-first precedent.** `ci-green`, `branch-protection`, and
  `required-checks` grade the *default branch's* runs or the repo's settings —
  nothing a PR's diff can change — so on `pull_request` events they are **demoted
  from required to recommended (warn)** via `MAIN_STATE_CHECKS` + `effective_severity()`
  (`cli.py:38`, `cli.py:41`; shipped v0.18.0, PR #65). This was done to break a
  bootstrap deadlock: "failing a PR for main's redness is how the fix-carrying PR
  gets deadlocked." Both new policies below lean on this precedent — **land a check
  advisory first, gate later.**
- **Fleet policy is pinned in `powderworks/housecaptain.toml`.** `[policy.checks]`
  sets fleet-wide severities; `[policy] locked = [...]` (dotted keys) escalates a
  key from expectation to law — a member that declares `fleet =` has locked keys
  enforced in its own audit at PR time (`captain.fleet_lock_rows`, `captain.py:561`),
  local overrides discarded. That is the lever for promoting either check to
  `required` fleet-wide once it's stable.

Two accuracy points that constrain what these policies can even ask for:

- **The 1500-line file-size budget is NOT in housekeeping.** It lives in the
  separate **straitjacket** repo (`DEFAULT_MAX_LINES = 1500`, `src/config.rs:67`;
  the whole-file rule at `engine.rs:373`, a `Severity::Error` that fails the run).
  housekeeping's own `straitjacket` check (`checks/straitjacket.py:13`) only verifies
  that straitjacket is *wired into CI* — it does not itself count lines. Any
  test-layout proposal has to compose *with* straitjacket's budget, not restate it.
- **housekeeping has NO changed-lines / changed-file / patch-scoping machinery.**
  Every check grades the whole tree (`ctx.workdir`) or API/settings state. The only
  "PR-context" that exists is the severity demotion above; the names "only" refer to
  the `--only` **check selector** (`cli.py:62`) and managed-config **fleet targeting**
  (`ManagedConfig.only`, `captain.py:77`) — **neither is diff scoping**. So any
  proposal that would need *patch coverage* (coverage of just the lines a PR touched)
  must say plainly: that machinery does not exist and would have to be built first.

---

## Policy A — Rust test layout

**The question.** Should the fleet discourage inline `#[cfg(test)] mod tests { … }`
blocks colocated in source files, in favour of sibling `foo/tests.rs` submodules or
top-level `tests/` integration dirs?

### The three layouts and where each is genuinely necessary

- **(a) Inline `#[cfg(test)] mod tests { … }`** at the tail of the source file.
  Full **unit access to private items** (it *is* a child module), zero ceremony —
  but it **bloats the file** and every one of those lines **counts against
  straitjacket's 1500-line budget**, which grades `.rs` files including their inline
  tests (`SIZE_EXTS`, straitjacket `engine.rs:44`).
- **(b) Sibling `foo/tests.rs` submodule** — `#[cfg(test)] mod tests;` in `foo.rs`,
  body in `foo/tests.rs`. Still `cfg(test)`, still a child module, so it **keeps
  private access** (`super::*` resolves exactly as before), while moving the bulk
  **out of the file that the budget grades.** This is the idiomatic middle ground.
- **(c) Top-level `tests/` integration dir** — a separate compiled crate,
  **public API only, no private access.** Necessary for round-trip / public-surface
  tests that *should* exercise the crate as a consumer would; it cannot substitute
  for unit tests that need private internals.

(a) is necessary only when a test genuinely needs private access *and* the module is
small; (b) is the right home for private-access tests once they get bulky; (c) is for
public-API/integration tests and is healthy fleet-wide already (every Rust repo uses
it — 15 integration files total). The live tension is purely **(a) vs (b)**.

### What the fleet actually looks like today

From the test-layout survey (measured, brace-matched spans — not regex):

| repo | inline `mod tests` | sibling `tests.rs` | largest inline module |
|---|---:|---:|---|
| disponent | 5 | **3** | 108 lines (`backend.rs`) |
| entl | 6 | 0 | 129 lines (`ingest.rs`) |
| fluessig | 5 | 0 | 157 lines (`readme.rs`) |
| straitjacket | 6 | 0 | 77 lines (`project.rs`) |
| **total** | **22** | **3** | **157** |

- **22 inline `mod tests` blocks** across the four Rust repos; only **disponent**
  uses the sibling pattern (**3** files), and even disponent-core is mixed (3 sibling,
  5 inline).
- Line-count violations if a "no inline test module over N lines" rule existed:
  **N=50 → 12/22** (55%), **N=100 → 6/22** (27%, fluessig holds 4 of them),
  **N=200 → 0**. The largest single inline module is fluessig `readme.rs` at **157**.
- **Zero inline blocks currently sit in an over-1500-line file.** The one file that
  ever crossed the budget — disponent `engine.rs` at 1562 — was already fixed by
  exactly the extraction below.

### The reference precedent — disponent's `engine.rs`

disponent commit **`f60b19b`** extracted `engine.rs`'s inline tests to
`engine/tests.rs` for precisely the budget reason: the env-provider/Compute split
pushed `engine.rs` to **1562 lines, over straitjacket's 1500 budget (CI error)**;
moving the inline `#[cfg(test)] mod tests` to a sibling `engine/tests.rs` was
"idiomatic, behavior-preserving (`super::*` still resolves)" and dropped it to
**1381 lines**, with **no production code changes.** That is the canonical pattern:
the tests were the cheapest ~180 lines to evict, and the extraction is mechanical.
disponent has since converged on the same form for `agent/tests.rs` and
`detectors/tests.rs`.

### Recommendation — **skip the hard mandate; document the sibling pattern**

**straitjacket's 1500-line budget is already the real forcing function, and it is the
one that actually fired.** It is what drove disponent's extraction. A separate
"no inline `mod tests` over N lines" housekeeping check would be a **rival threshold
that double-counts** the same lines straitjacket already grades — and the data says
the pain is small: **max inline module 157 lines, nothing over 200, nothing currently
in an over-budget file.** A hard N-line mandate at N≤100 would flag a dozen perfectly
reasonable 60–90-line modules for no incremental safety.

So:

1. **Sanction disponent's `foo/tests.rs` sibling pattern as the documented remedy**
   the file-size budget points people to. When straitjacket flags a file as
   over-budget and its inline tests are the cheapest lines to evict, the sanctioned
   move is extraction to `foo/tests.rs` — `super::*` still resolves, no production
   change. This is documentation, not a check.
2. **If a check is wanted at all, make it ADVISORY and compose with straitjacket
   rather than add a new number.** Don't gate on an independent line count. Flag an
   inline test module only when it is a **material contributor to a file that is near
   or over the 1500 budget** — i.e. reuse straitjacket's own threshold, and only
   nudge ("this 129-line inline test module is the cheapest split if `ingest.rs`
   crosses the budget") rather than invent a second ceiling. Escape hatch mirrors
   straitjacket's `straitjacket-allow-file:file-size`.

Proposed shape, *if* built:

```python
@check("test-layout", needs=("clone",))
def test_layout(ctx: RepoContext) -> Result:
    # Advisory only (severity=recommended, config.py:DEFAULT_SEVERITY).
    # For each .rs file within ~85% of straitjacket's max-lines budget
    # (read from the repo's .straitjacket.yaml, default 1500), if a large
    # inline `#[cfg(test)] mod tests { … }` is a material share of the file,
    # suggest extracting it to a sibling `foo/tests.rs`. Never independent
    # of the budget; never a second line count. Escape hatch: same
    # straitjacket-allow-file:file-size marker.
    ...
```

It would **not** join `MAIN_STATE_CHECKS` — it grades the tree, which a PR can
change, so it should gate normally *if* ever promoted (it should not be, initially).

---

## Policy B — Coverage mandate

**The question.** Should the fleet mandate a code-coverage floor, and if so, how?

### What's measured today

Real `cargo-llvm-cov` on stable 1.97.0 (`llvm-tools-preview`, no nightly):

| crate | lines covered | notable holes |
|---|---:|---|
| **disponent-core** | **~80.2–80.6 %** | `mcp_generated.rs` 0 % (75/75, a generated file); `backend.rs` 70.9 % (stubbed remote paths) |
| **fluessig (core)** | **72.10 %** | `bin/fluessig-gen.rs` 0 % (165), `codegen.rs` 0 % (154) — generator binaries drag it down; **library proper ~86 %** |

**No coverage gating exists anywhere in the fleet today** — no `coverageThreshold`,
no `pytest-cov`, no tarpaulin/llvm-cov/codecov in any `Cargo.toml`, `bunfig.toml`,
`pyproject.toml`, or workflow. These are the first real figures.

### Per-language tooling

- **Rust → `cargo-llvm-cov`** (recommend). Runs on **stable** + `llvm-tools-preview`
  (NOT nightly — "needs nightly" is a myth for both llvm-cov and tarpaulin). Precise
  region/line/function data; `--fail-under-lines N` built in. Cost is only
  **~1.0–1.2× `cargo test`** cold, *but* it keeps a **separate instrumented
  `target/llvm-cov-target` dir**, so a repo that also runs plain `cargo test` pays
  **two full compiles** — budget "coverage ≈ +1 full build" per crate. tarpaulin is
  the alternative — Linux-x86_64-only, ptrace, line-only, flakier on FFI/threads —
  so **llvm-cov is the right default.**
- **Bun → `bun test --coverage`** (built-in, no dep). Per-file table + LCOV; **global
  threshold only** via `bunfig.toml` `[test] coverageThreshold`. **No per-file, no
  patch mode.**
- **Python → `pytest-cov`** (`--cov --cov-fail-under=N`). **Not configured today** —
  entl-python's dev group has no `pytest-cov`.

### The binding-crate blind spot (state honestly)

This ties directly to disponent/entl's **"honest capability edges"** ethos — mark
what's exact vs derived, never fake success. The napi/pyo3/magnus crates
(`disponent-node`, `entl-node`, `entl-python`, `entl-ruby`) are **excluded from
`default-members`** and build via `napi` / `maturin` / `rb_sys`, so a plain
`cargo llvm-cov` **never even compiles them.** Their Rust is exercised through
bun/pytest/minitest against a compiled `.node`/`.so` — invisible to *both* llvm-cov
(no hook into a bun/pytest process loading a prebuilt native addon) *and* to
bun/pytest coverage (which sees only the JS shim `index.js` at ~11 % / the Python
`entl.models`, not the compiled extension). Counting them would need bespoke
instrumented-native-build plumbing (`RUSTFLAGS=-C instrument-coverage` +
`cargo llvm-cov --no-run` producing the addon, run the bun/pytest suite against
*that*, then merge `.profraw`) — roughly doubles that crate's CI build and
cross-language profraw merging is fiddly. **A coverage % that silently omitted these
crates would be dishonest** — it must be explicitly scoped and marked as a gap.

### Threshold shapes

- **Global % floor** — cheapest, one number, supported by all three toolchains; but
  most distorted by generated/entrypoint files (the 0 % files above drag both crates
  down several points).
- **Per-file floor** — lets you exempt generated files (`mcp_generated.rs`,
  `codegen.rs`, `bin/fluessig-gen.rs`) instead of letting them sink the number, but
  needs a wrapper over the `--json`/lcov output (bun and pytest-cov don't gate
  per-file natively). Moderate effort.
- **Changed-lines "patch coverage"** — the best signal-to-noise for a *new* mandate
  (doesn't demand back-filling legacy gaps) and what people actually want — **but it
  REQUIRES the changed-files machinery housekeeping does not have** (see the accuracy
  point above). **Build-first, not now.**

### Recommendation — **adopt-advisory**

> **Superseded — see [Review decision (2026-07-09)](#review-decision-2026-07-09).** The
> check was accepted but **narrowed to presence-only**: it verifies a coverage tool is
> *configured* per ecosystem, and does **not** report a %, enforce a floor, or read
> `[coverage] min`. The threshold/percent shapes below are the original proposal, kept
> as history.

Add a **`coverage` check at `severity=recommended`**, explicitly following the
`ci-green` advisory-first precedent: land it advisory, gate later. It **reports the
%** and passes/warns without gating initially — **no floor, or a floor set below
current reality** (e.g. 70 % global) purely to catch *regression*, not to demand
back-fill. disponent (~80 %) and fluessig (72 %) are **green today** at a 70 % floor,
so this is non-disruptive on day one.

- **Do NOT attempt patch coverage yet** — the machinery is absent (§ accuracy point).
- **Scope the number to what's actually measured** and **mark the binding crates as an
  explicit gap** in the check's own note ("core/CLI only; napi/pyo3/magnus Rust is
  tested through bun/pytest and not counted") — honest capability edges.
- **Path to `required`:** once each repo's floor is set and stable, pin per-repo
  minimums in `powderworks/housecaptain.toml` `[policy] locked` and promote to
  `required`. Not before.

Proposed shape:

```python
@check("coverage", needs=("clone",))
def coverage(ctx: RepoContext) -> Result:
    # severity=recommended by default (config.py:DEFAULT_SEVERITY), following
    # the ci-green advisory-first precedent. Ecosystem detection (ctx.ecosystems)
    # picks the runner: Rust -> cargo-llvm-cov --summary-only (stable +
    # llvm-tools-preview); bun -> bun test --coverage; python -> pytest-cov.
    # Reports the measured % as the Result detail. Floor read from
    # ctx.config.section("coverage") (e.g. min = 70); absent = report-only.
    # NOTE in the Result: default-members/core only — binding crates
    # (napi/pyo3/magnus) are not counted (blind spot), stated, not hidden.
    ...
```

Like `test-layout`, `coverage` grades the tree, so it is **not** a `MAIN_STATE_CHECK`.

---

## Fleet migration cost

- **Test layout — 0 required migrations today.** Nothing is over the 1500 budget, so
  a hard mandate would demand no changes and an advisory would emit ~3 near-term
  nudges at most: the same-shape-as-`engine.rs` files, **entl `ingest.rs`** (993 total,
  129 test → ~864 after extraction) and **disponent `backend.rs`** (821 total, 108
  test → ~713). Both are prevention, not a live fire.
- **Coverage — the work is wiring, not raising numbers.** disponent (~80 %) and
  fluessig (72 %) already clear an advisory 70 % floor; **entl** is unmeasured but
  the same shape. The cost is wiring the per-language runner into each repo's CI
  (and paying the +1 instrumented build), **not** hitting a target.

## Recommendation summary

| Policy | Verdict | Proposed check | Severity | Migration cost |
|---|---|---|---|---|
| **Test layout** | **Skip the mandate; document the sibling pattern** (+ optional advisory lint that composes with straitjacket's budget) | none required; optional `test-layout` | recommended (if built) | 0 required today; ~3 advisory nudges (`ingest.rs`, `backend.rs`) |
| **Coverage** | **Adopt-advisory** | `coverage` (per-language runner) | recommended → required later via `housecaptain.toml [policy] locked` | wiring per repo; 70 % floor green today |

## Open questions — which pieces to build?

**Nothing is being implemented yet.** To turn this note into work, decide:

- **Test layout —** just *document* the `foo/tests.rs` sibling pattern as the
  sanctioned remedy the file-size budget points to, **or** also ship the advisory
  `test-layout` lint that composes with straitjacket's budget? (Recommendation: document
  first; the lint is optional and low-value given the data.)
- **Coverage —**
  - Ship the advisory `coverage` check now?
  - **Which repos first?** (disponent + fluessig already measure clean; entl needs a
    first run.)
  - **What global floor** — none (report-only), or a regression floor like 70 %?
  - **When to promote any repo to `required`** via `housecaptain.toml [policy] locked`,
    and at what per-repo minimum?
  - Confirm we are **not** attempting patch coverage until the changed-files machinery
    is built as a separate piece of work.

---

## Review decision (2026-07-09)

The note was reviewed and both policies decided. Recording the outcomes so the
proposals above read as history, not open questions.

- **Test layout — skip the mandate (accepted).** No enforcement check is built.
  straitjacket's 1500-line file-size budget is already the real forcing function and
  the only one that has actually fired; a rival housekeeping line count would
  double-count the same lines. The **sanctioned remedy** when the budget bites is
  disponent's sibling `foo/tests.rs` pattern — `#[cfg(test)] mod tests;` in `foo.rs`
  with the body in `foo/tests.rs`, which keeps private access (`super::*` still
  resolves) while moving the bulk out of the graded file. That is **documentation, not
  a check** (the optional advisory `test-layout` lint sketched in Policy A is **not**
  being built). See disponent `f60b19b` for the canonical extraction.

- **Coverage — build an advisory presence check (accepted).** Scope is **narrowed from
  the threshold-reporting proposal in Policy B to PRESENCE-ONLY.** The check verifies
  only that *a coverage tool is configured* for each detected ecosystem — each repo
  configures the specifics as makes sense. It does **not** measure a coverage %, does
  **not** enforce a threshold, and does **not** do patch/changed-lines coverage (so the
  binding-crate blind spot and the missing changed-files machinery both stop being
  blockers — presence is cheap and honest to check). Default severity **`recommended`**,
  following the `ci-green` advisory-first precedent, so it does not turn the fleet red
  on landing (no repo wires coverage yet). Promotion to `required` remains a later,
  per-repo move via `powderworks/housecaptain.toml [policy] locked` once repos wire it.
  Implemented in a follow-up PR — see follow-up PR (`feat/coverage-presence-check`).

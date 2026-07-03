---
name: tidy-up
description: Audit the current GitHub repo with housekeeper (branch protection, CI, dependabot, secret scanning, lockfiles, README, website, license) and drive confirm-first fixes, including a README quality pass. Use when the user asks to housekeep, audit, or tidy up a repo, or asks "is this repo in good order?"
---

# Tidy up a repo

You drive `housekeeper`, a deterministic repo auditor. You interpret its
results and help fix them — you do not re-derive the checks yourself.

## Prerequisites

The skill needs the `housekeeper` CLI and an authenticated `gh`. If
`housekeeper` is missing, offer to install it:

```sh
uv tool install git+https://github.com/zmaril/housekeeping
```

(If `uv` is also missing, point the user at https://docs.astral.sh/uv/ rather
than picking an install method for them.)

## Run the audit

```sh
housekeeper check              # inside a checkout, or:
housekeeper check owner/repo
```

Read the JSON it saves (path is printed, under `~/.cache/housekeeping/results/`)
rather than parsing the table.

## Interpret

- Explain each **fail** in plain language: what's wrong, why it matters, what
  fixing it involves. Group by effort — API-side toggles vs. changes that need
  commits.
- **skip** results are fine; mention the note only if it's actionable.
- **warn** (recommended-severity fails) are worth a sentence, not a lecture.

## Fix

Offer fixes one at a time, most valuable first (branch protection and
dependabot are usually the cheapest wins). For each one the user wants:

```sh
housekeeper fix <check-name>
```

The fix explains itself and asks for confirmation before changing anything —
let the user answer the prompts; do not pipe `yes` into it. File-side fixes
land on a `housekeeping/<check>` branch and only push/PR on an explicit yes.

Checks without automated fixes (`ci-green`, `website`, `stale`) need real
work: investigate the failing run, fix the dead link, close the stale PR.
Do that work with the user rather than telling them to.

## README quality pass

The `readme` check is a deterministic floor (title, sections, word count,
unbroken links). When it fails on substance, or passes and the user wants the
README actually *good*, do the judgment pass yourself:

Read the README as a stranger who just landed on the repo, against one
question: **in 30 seconds, do I know what this is, why I'd want it, and how
to start?** Work through, in order:

1. **First screen** — name, one-line pitch, proof it's alive (badge,
   screenshot, example output). If the pitch buries the lede or reads like
   marketing, say what the honest one-liner is.
2. **Why** — what problem, for whom, and what they'd use otherwise. A README
   that only says *what* leaves the reader to guess *why*.
3. **Start** — can the install + first-use path be copy-pasted top to bottom
   and work? Flag steps that assume unstated tools or context.
4. **Depth cues** — links out to real docs, changelog, license, contributing.
   Not everything belongs in the README; check it delegates.
5. **Rot** — claims that no longer match the code (flags, versions, feature
   lists). Cross-check anything checkable against the repo itself.

Then **draft the edits** — concrete replacement text, not a critique memo.
Propose the smallest set of changes that fixes what you found. Match the
repo's existing voice; do not sand the personality off a README that has one.

## Powderworks cross-promotion (zmaril repos only)

Only when the repo owner is **zmaril** and the project is part of the
powderworks family: check the README for a short section pointing readers at
sibling projects they might like. If it's missing, draft one — two to four
lines, matching the repo's voice, linking siblings that a reader of *this*
tool would plausibly want:

- [Straitjacket](https://github.com/zmaril/Straitjacket) — deterministic
  scanner for the weird code and text LLMs like to produce
- [housekeeping](https://github.com/zmaril/housekeeping) — checks that a
  GitHub repo is in good order, and helps fix it
- [powdermonkey](https://github.com/zmaril/powdermonkey) — agent
  orchestration harness for aspiring slop cannons

Keep this list current as the family grows. Skip this section entirely for
repos that aren't zmaril's — it's family business, not part of the audit.

## Config

Per-repo overrides live in `.housekeeping.toml` at the repo root:

```toml
[checks]
website = "off"          # or "recommended" / "required"

[website]
url = "https://example.dev"   # expected homepage, overrides the repo setting
```

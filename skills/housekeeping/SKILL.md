---
name: housekeeping
description: Audit the current GitHub repo with housekeeper (branch protection, CI, dependabot, lockfiles, straitjacket, README, website, license) and drive fixes interactively. Use when the user asks to housekeep, audit, or tidy up a repo, or asks "is this repo in good order?"
---

# Housekeeping

You drive `housekeeper`, a deterministic repo auditor. You interpret its
results and help fix them — you do not re-derive the checks yourself.

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

For a failing `readme` check — or a passing one the user wants better — use
the `readme-review` skill.

## Config

Per-repo overrides live in `.housekeeping.toml` at the repo root:

```toml
[checks]
website = "off"          # or "recommended" / "required"

[website]
url = "https://example.dev"   # expected homepage, overrides the repo setting
```

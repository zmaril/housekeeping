---
name: readme-review
description: Judgment pass on a repo's README quality — is it actually good, not just structurally complete? Use after housekeeper's readme check, or when the user asks whether their README is any good.
---

# README review

The deterministic floor (title, sections, word count, unbroken links) is
`housekeeper check --only readme`'s job. Yours is taste.

Read the README as a stranger who just landed on the repo. Judge it against
one question: **in 30 seconds, do I know what this is, why I'd want it, and
how to start?**

Work through, in order:

1. **First screen** — name, one-line pitch, and proof it's alive (badge,
   screenshot, example output). If the pitch buries the lede or reads like
   marketing, say what the honest one-liner is.
2. **Why** — what problem, for whom, and what they'd use otherwise. A README
   that only says *what* leaves the reader to guess *why*.
3. **Start** — can the install + first-use path be copy-pasted top to bottom
   and work? Flag steps that assume unstated tools or context.
4. **Depth cues** — links out to real docs, changelog, license,
   contributing. Not everything belongs in the README; check it delegates.
5. **Rot** — claims that no longer match the code (flags, versions, feature
   lists). Cross-check anything checkable against the repo itself.

Then **draft the edits** — concrete replacement text, not a critique memo.
Propose the smallest set of changes that fixes what you found, as a diff or
rewritten sections the user can apply directly. Match the repo's existing
voice; do not sand the personality off a README that has one.

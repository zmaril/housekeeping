# Agent guide

How agents work in this repo. The human is Zack; the taste is his.

## PRs

- **PR titles are conventional commits**: `type(scope): summary`, types
  `feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert`. The
  `conventional` workflow rejects anything else, and squash merges inherit
  the PR title — a sloppy title becomes a sloppy permanent commit on main.
- **Never merge.** Open the PR, get every check green, hand over the link.
  Zack reviews and merges everything himself. Closing your own PR when asked
  is fine; merging is not.
- Main is protected: all changes go branch → PR → required checks (`test`,
  `straitjacket`) → Zack.

## Before pushing

- `uv run pytest` and `uv run ruff check .` — both clean.
- CI also runs [straitjacket](https://github.com/zmaril/Straitjacket) over
  code *and prose*: no emoji in source, no duplicated blocks, no slop text.
- `uv run housekeeper check` must exit 0 on this repo. A new check lands only
  if housekeeping itself passes it — this repo eats its own dog food first.

## Writing checks

See the check contract in [notes/design.md](notes/design.md). House rules: checks are
read-only; fixes explain what and why, confirm before touching anything,
write to `housekeeping/<check>` branches, and never push to a default
branch. Skips always say why. Caps on coverage are stated in the output,
never silent.

## Releases

Version numbers exist only for the GitHub Action contract
(`uses: zmaril/housekeeping@v1`). When a merged change alters what `@v1`
does — a new check, a changed verdict, a fixed false negative — the change
is not shipped until the release ceremony: immutable `vX.Y.Z` tag,
fast-forward `v1`, GitHub release, changelog entry titled `vX.Y.Z — date`.
Changes that don't touch Action behavior get date-only changelog entries and
no tag. Cutting a release requires Zack's go-ahead, same as merging.

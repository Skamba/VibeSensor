---
applyTo: "docs/**"
---
Docs
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures docs-specific deltas.
- Keep `docs/` short and focused. Add design changes (e.g. report layout) to `docs/design_language.md`.
- For any user-visible text changes, update `apps/server/data/report_i18n.json` and mention new keys in docs.
- Rewrite or remove stale sections aggressively; do not keep contradictory historical guidance in place.
- Prefer direct pointers to current source-of-truth files over long prose that will drift.
- When architecture, file ownership, commands, or workflows change, update the matching repo maps, runbooks, READMEs, and instruction files in the same change set.

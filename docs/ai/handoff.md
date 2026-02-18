# Minimal AI Change Request Template

Use this format for future AI requests. Keep it short.

## 1) Goal
- One paragraph: what must change and why.

## 2) Constraints
- Non-negotiables (performance, compatibility, UX, safety, scope).
- Output discipline (low-noise, avoid large logs in chat).

## 3) Affected Area
- Pick from `docs/ai/map.md` (module boundary + hot spot/safe area).

## 4) Files to Touch (initial guess, max 10)
- List expected files.

## 5) Validation
- Narrow checks only (exact commands).

## 6) Deliverable
- Expected changed files + acceptance criteria.

---

## Agent Rules (strict)
1. Read `docs/ai/context.md`, `docs/ai/map.md`, `docs/ai/runbooks.md`, `docs/ai/decisions.md` first.
2. Read no more than 10 additional files before first patch unless blocked.
3. Prefer scoped searches (`rg` with globs/folders), not repo-wide scans.
4. Keep terminal output short; write verbose logs to `artifacts/ai/logs/`.
5. Run narrow validation first; widen only if needed.

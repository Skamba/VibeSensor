# AI Change Request Template

Use this format for future AI requests.

## 1) Goal
- One paragraph: what must change and why.

## 2) Constraints
- Non-negotiables (performance, UX, safety, scope). Backward compatibility is optional and never required.
- Output discipline (low-noise, avoid large logs in chat).

## 3) Affected Area
- Pick from `docs/ai/map.md` (module boundary + hot spot/safe area).

## 4) Files to Touch (initial guess)
- List expected files.

## 5) Validation
- Start with targeted checks, then run CI-aligned checks (`make test-all`) before finalizing.
  - `make test-all` maps to `tools/tests/run_ci_parallel.py` and runs CI-equivalent `preflight`, `tests`, and `e2e` groups in parallel locally.

## 6) Deliverable
- Expected changed files + acceptance criteria.

---

## Agent Rules
1. Read `docs/ai/context.md`, `docs/ai/map.md`, `docs/ai/runbooks.md`, `docs/ai/decisions.md` first.
2. Start focused, but read additional files as needed for larger cross-cutting changes.
3. Prefer scoped searches (`rg` with globs/folders), not repo-wide scans.
4. Keep terminal output short; write verbose logs to `artifacts/ai/logs/`.
5. Run targeted validation early, then complete CI-aligned validation before handoff.

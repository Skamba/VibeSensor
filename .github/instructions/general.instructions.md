---
applyTo: "**"
---
Canonical agent workflow (shared source of truth)
- Read `docs/ai/repo-map.md` first.
- For medium/large tasks, always start with an explicit checklist plan. Use highly descriptive titles that include the problem, the fix, and user impact.
- Work in iterative loops until done: `plan → verify current behavior → root cause → blast radius scan → implement minimal change → targeted tests → broader relevant tests → re-plan`.
- Verify existing behavior before rewriting code; investigate root cause before patching symptoms.
- Scan the blast radius for similar in-scope issues and fix them in the same run.
- Prefer extending and hardening existing logic over adding parallel implementations.
- Continue autonomously on clearly adjacent in-scope issues without waiting for another prompt.
- Stop only when one of these conditions is true:
  1. all plan items are complete and validated,
  2. no similar in-scope issues remain,
  3. a real blocker exists (credentials/hardware/external dependency),
  4. time budget is reached.
- Long, thorough runs are allowed and preferred for deeper tasks; a 45–60 minute run is acceptable for medium/large changes.
- Context/noise control:
  - avoid scanning generated/build/cache/vendor artifacts unless debugging them (`artifacts/`, `.cache/`, `node_modules/`, `dist/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`),
  - use focused file reads and scoped searches,
  - avoid huge command output unless needed.
- No-cheating implementation rules:
  - put executable logic in proper code files, not hidden in docs/json/txt wrappers,
  - when adding large inline data definitions, move them into appropriate data files (`.json`, `.yaml`, etc.),
  - do not create duplicate parallel implementations when extending existing logic is cleaner.

Updater deployment policy
- Treat updater delivery as wheel-first. Runtime fixes must land in repo code and flow through PR/CI; avoid relying on ad-hoc runtime file edits.
- Emergency-only exception: if updater path is broken on a live device, temporary in-place patching on the device is allowed strictly to restore service.
- After any emergency in-place patch, complete the follow-up loop in the same run when feasible: repo fix + tests/lint + PR green + merge + successful updater rerun on device.

Validation (always required)
- Pull request default mode: after opening or updating a PR, check CI/review status, fix all blocking issues, push updates, and keep monitoring until required checks are green.
- For every PR, use `python3 tools/ci/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor` as the default monitor.
- Treat watcher exit `RESULT=NON_GREEN` as fail-fast: inspect the latest failing run immediately, implement the minimal fix, push, and restart the watcher.
- Treat watcher exit `RESULT=ALL_GREEN` as the merge-ready gate for CI checks.
- Test in this order: targeted tests first, then broader relevant suites.
- CI-parity suite (same command groups as `.github/workflows/ci.yml`, run in parallel locally): `make test-all` (`python3 tools/tests/run_ci_parallel.py`).
- Optional CI-parity subset jobs for faster loops: `python3 tools/tests/run_ci_parallel.py --job preflight --job tests`.
- Optional focused backend pytest: `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Run lint (`ruff check`) before pushing changes.
- After any backend or frontend change, rebuild and test via Docker before considering the work done:
  1. `docker compose build --pull`
  2. `docker compose up -d`
  3. `docker compose ps`
  4. `vibesensor-sim --count 5 --duration 10 --no-interactive`
  5. confirm `http://127.0.0.1:8000` updates live while the simulator runs,
  6. verify updates stop after the simulator stops (no stale-data artifacts),
  7. check `docker compose logs --tail 50` if needed.
- Breaking changes are generally allowed when intentional.
- Compatibility exception: preserve parsing compatibility for old recorded runs/report data unless the task explicitly waives it.

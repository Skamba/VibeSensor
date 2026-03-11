---
applyTo: "**"
---
Canonical agent workflow (shared source of truth)
- Read `docs/ai/repo-map.md` first.
- For medium/large tasks, always start with an explicit checklist plan. Use highly descriptive titles that include the problem, the fix, and user impact.
- Work in iterative loops until done: `plan → verify current behavior → root cause → blast radius scan → implement complete maintainable fix → targeted tests → broader relevant tests → re-plan`.
- Verify existing behavior before rewriting code; investigate root cause before patching symptoms.
- Scan the blast radius for similar in-scope issues and fix them in the same run.
- Prefer extending and hardening existing logic over adding parallel implementations.
- When a larger refactor or other major in-scope change is the clearest path to better long-term maintainability, prefer that over a narrowly local patch that preserves poor structure.
- Analysis-first default: examine the issue from multiple angles, choose the strongest approach, and deliver the smallest validated **complete** in-scope fix that addresses root cause and nearby in-scope blast radius.
- Avoid symptom-only patches. Prefer fixes that make sense to a human maintainer and reduce future maintenance burden in the touched area.
- Avoid over-conservative blocking behavior: do not hold a clear fix for exhaustive hypothetical analysis.
- Use bounded risk rather than risk avoidance: keep changes reversible, validate early, and recover quickly on failures.
- Continue autonomously on clearly adjacent in-scope issues without waiting for another prompt.
- Stop only when one of these conditions is true:
  1. all plan items are complete and validated,
  2. no similar in-scope issues remain,
  3. a real blocker exists (credentials/hardware/external dependency),
  4. the user explicitly asks to pause.
- Long, thorough runs are allowed and preferred for deeper tasks; multi-hour runs are acceptable when needed to complete in-scope work well.
- Context/noise control:
  - avoid scanning generated/build/cache/vendor artifacts unless debugging them (`artifacts/`, `.cache/`, `node_modules/`, `dist/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`),
  - use focused file reads and scoped searches,
  - avoid huge command output unless needed.
- No-cheating implementation rules:
  - put executable logic in proper code files, not hidden in docs/json/txt wrappers,
  - when adding large inline data definitions, move them into appropriate data files (`.json`, `.yaml`, etc.),
  - do not create duplicate parallel implementations when extending existing logic is cleaner.

Complexity hygiene
- Remove config fields that are not read by any code path. Do not add speculative config knobs.
- Maintain a single source of truth for default values; do not duplicate defaults across files.
- Do not add forward-extensibility machinery (overflow columns, plugin hooks, generic registries) until a concrete second consumer exists.
- Prefer flat, direct structures. Only introduce grouping or wrapping when more than three consumers benefit from the indirection.
- Do not create sub-packages for single-consumer, single-export modules. A flat module file is preferred until 3+ distinct consumers exist.
- Do not create Protocol types for single-implementor classes. Use the concrete type directly.
- Do not add compatibility aliases or shims when refactoring. Update all consumers directly in the same change set.
- Do not create wrapper dataclasses for one-shot operations (constructed only to call a single method and then discarded).
- Do not create TypedDict mirrors of Pydantic models. Use Pydantic for HTTP boundaries and TypedDicts only for WebSocket/non-Pydantic dict construction.
- Route handlers must be thin HTTP translators. Extract business logic into service functions that are independently testable.
- Do not create duplicate API endpoints for the same operation.
- Do not create standalone Python scripts for simple pytest flag combinations. Use Makefile recipes directly.
- Do not create Makefile aliases that are documented as "use X instead". Remove the alias.
- Prefer few large modules over many tiny modules when the modules serve a single consumer.

Documentation maintenance (always required)
- After every meaningful code change, check whether docs, repo maps, runbooks, READMEs, and instruction files that reference the touched area are now stale.
- Update stale documentation in the same change set; do not leave documentation drift for later unless the user explicitly asks you not to touch docs.
- Remove or rewrite obsolete guidance instead of layering caveats on top of it.
- Keep human-facing docs and AI-facing guidance aligned with the live code, paths, commands, and ownership boundaries.

Updater deployment policy
- Treat updater delivery as wheel-first. Runtime fixes must land in repo code and flow through PR/CI; avoid relying on ad-hoc runtime file edits.
- Emergency-only exception: if updater path is broken on a live device, temporary in-place patching on the device is allowed strictly to restore service.
- After any emergency in-place patch, complete the follow-up loop in the same run when feasible: repo fix + tests/lint + PR green + merge + successful updater rerun on device.

Validation (always required)
- Pull request default mode: after opening or updating a PR, check CI/review status, fix all blocking issues, push updates, and keep monitoring until required checks are green.
- For every PR, use `python3 tools/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor` as the default monitor.
- Treat watcher exit `RESULT=NON_GREEN` as immediate action: inspect the latest failing run promptly, determine root cause, implement the smallest complete maintainable fix, push, and restart the watcher.
- Treat watcher exit `RESULT=ALL_GREEN` as the merge-ready gate for CI checks.
- Test in this order: targeted tests first, then broader relevant suites.
- CI-parity suite (same command groups as `.github/workflows/ci.yml`, run in parallel locally): `make test-all` (`python3 tools/tests/run_ci_parallel.py`).
- Optional CI-parity subset jobs for faster loops: `python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests`.
- Run a single feature area: `pytest -q apps/server/tests/<module>/` (e.g., `tests/analysis/`, `tests/report/`).
- Test layout: feature-based subdirectories mirror source modules; see `docs/testing.md`.
- If an intentional refactor changes function-level seams or helper boundaries, refactor the affected tests in the same change set so they validate current behavior instead of pinning obsolete internals.
- Run lint (`ruff check`) and backend type checks (`make typecheck-backend`) before pushing changes.
- After any backend or frontend change, rebuild and test via Docker before considering the work done:
  1. `docker compose build --pull`
  2. `docker compose up -d`
  3. `docker compose ps`
  4. `vibesensor-sim --count 5 --duration 10 --no-interactive`
  5. confirm `http://127.0.0.1` updates live while the simulator runs (`:80` default; if `:80` is not serving in the current config, try `http://127.0.0.1:8000` as the backup/dev port),
  6. verify updates stop after the simulator stops (no stale-data artifacts),
  7. check `docker compose logs --tail 50` if needed.
- Breaking changes are allowed when intentional.
- No-backward-compatibility policy: we own the full codebase end to end. Do not add or preserve backward-compatibility layers (deprecated paths, adapters, fallbacks, shims, version-bridging logic, or legacy schema support) unless explicitly asked. Remove them when encountered. Standardize on the current contract, schema, config, and runtime path. Do not add new compatibility code "just in case". If compatibility seems necessary, flag it explicitly rather than implementing it silently.

Docs (`docs/`)
- Keep `docs/` short and focused. Add design changes (e.g. report layout) to `docs/design_language.md`.
- For any user-visible text changes, update `apps/server/data/report_i18n.json` and mention new keys in docs.
- Rewrite or remove stale sections aggressively; do not keep contradictory historical guidance in place.
- Prefer direct pointers to current source-of-truth files over long prose that will drift.
- When architecture, file ownership, commands, or workflows change, update the matching repo maps, runbooks, READMEs, and instruction files in the same change set.

Infra / Docker / CI (`docker-compose.yml`, `.github/workflows/`)
- Local dev: `docker compose build --pull` then `docker compose up -d`.
- CI: `.github/workflows/ci.yml` is authoritative for blocking job commands (`backend-quality`, `backend-typecheck`, `frontend-typecheck`, `ui-smoke`, `backend-tests`, `e2e`).
- Local CI-parity run: `make test-all` (runs `python3 tools/tests/run_ci_parallel.py`, which mirrors those CI job command groups in parallel).
- Keep CI steps maintainable; larger CI/workflow updates are allowed when needed. If adding new test dependencies, update `apps/server/pyproject.toml` so CI installs them via the editable install.
- Avoid embedding secrets in workflow files; use repository secrets for tokens.

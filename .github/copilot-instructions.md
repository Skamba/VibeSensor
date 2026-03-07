Repository overview
- VibeSensor has a Python backend in `apps/server/`, a TypeScript/Vite dashboard in `apps/ui/`, simulator tooling in `apps/simulator/`, and device/firmware assets under `firmware/esp/`, `hardware/`, and `infra/pi-image/`.
- Backend architecture is package-based: `app.py` creates the FastAPI app, `bootstrap.py` wires services, `routes/` owns HTTP/WebSocket route groups, `runtime/` owns runtime coordination, `history_db/` owns SQLite persistence, `report/` owns PDF rendering, and `update/` owns wheel-based updates.
- Key runtime artifacts are `docker-compose.yml` at repo root and `apps/server/pyproject.toml` for backend packaging and CLI entry points.
- Units policy: raw ingest/sample acceleration values may use g, but post-stop analysis outputs (persisted summaries, findings, report-template artifacts) must expose vibration strength or intensity in dB only.
- Canonical dB definition: `libs/core/python/vibesensor_core/vibration_strength.py::vibration_strength_db_scalar()` (`20*log10((peak+eps)/(floor+eps))`, `eps=max(1e-9, floor*0.05)`).

Source-of-truth note
- This file is the canonical short AI guide; `AGENTS.md` and `CLAUDE.md` should remain pointers to this file to prevent drift.

Canonical instruction sources
- Read `docs/ai/repo-map.md` first.
- Shared workflow and validation guardrails live in `.github/instructions/general.instructions.md`.
- Area-specific deltas live in `.github/instructions/{backend,frontend,tests,infra,docs,report}.instructions.md`.

Execution model
- For medium or large tasks, start with an explicit checklist plan whose item titles include problem, fix, and user impact.
- Iterate until complete: `plan → verify existing behavior → root cause → blast radius scan → implement complete maintainable fix → targeted tests → broader relevant tests → re-plan`.
- Prefer extending or hardening existing logic over parallel implementations.
- Analysis-first default: evaluate the problem from multiple angles, compare viable options, then choose the best path to deliver a complete root-cause fix with thorough in-scope coverage.
- Do not stop at symptom-only patches; when touching an issue, resolve the underlying cause and tightly coupled maintainability gaps in the same area.
- Avoid over-conservative blocking behavior: do not delay a clear in-scope fix for exhaustive hypotheticals or speculative edge cases.
- Use bounded risk, not risk avoidance: keep changes reversible, test quickly, and correct fast when validation fails.
- Continue autonomously on clearly adjacent in-scope issues.
- Stop only when all plan items are validated complete, no similar in-scope issues remain, a real blocker exists, or the time budget is reached.
- Long deep runs are allowed and preferred for medium or large work.

Documentation maintenance
- After every meaningful code change, check whether docs, repo maps, runbooks, READMEs, and instruction files that reference the touched area are now stale.
- Update stale documentation in the same change set. Do not leave documentation drift for later unless the user explicitly says not to update docs.
- Remove or rewrite obsolete guidance instead of appending caveats to outdated sections.
- Keep human-facing docs (`README.md`, `apps/server/README.md`, `docs/**`) and AI-facing guidance (`docs/ai/**`, `.github/**/*.instructions.md`, `.github/copilot-instructions.md`) aligned with the live codebase.

Updater delivery model (authoritative)
- Production updater behavior is wheel-based: devices fetch release wheels and install them through `apps/server/vibesensor/update/manager.py`.
- Do not treat in-place edits under `/opt/VibeSensor/.../site-packages` as a normal deployment mechanism.
- Emergency-only exception: direct on-device patching is allowed for live incident mitigation when the updater path itself is broken.
- If emergency patching is used, always follow up by:
	1. implementing the same fix in repo,
	2. validating tests and lint,
	3. opening and merging a PR,
	4. re-running the updater successfully so the device returns to wheel-managed state.

Common commands
- `python -m pip install -e "./apps/server[dev]"`
- `make lint`
- `make typecheck-backend`
- `make docs-lint`
- `make test-all` (CI-parity local suite: `backend-quality` + `backend-typecheck` + `frontend-typecheck` + `ui-smoke` + `backend-tests` + `e2e` jobs in parallel)
- `python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests` (faster backend-focused CI subset)
- `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`
- `pytest -q apps/server/tests/<module>/` (run tests for a single feature area)
- `python3 tools/ci/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor`
- `cd apps/ui && npm ci && npm run typecheck && npm run build`
- `docker compose build --pull && docker compose up -d`

Test layout
- Tests are organized in feature-based subdirectories under `apps/server/tests/` mirroring source modules. See `docs/testing.md` for the full map.
- Mapping rule: if you change `vibesensor/<module>/`, tests live in `tests/<module>/`.
- Cross-cutting tests live in `tests/integration/` for scenario and multi-module coverage, `tests/regression/` for intent-grouped bug-fix regressions, `tests/hygiene/` for architecture guards, and `tests/e2e/` for browser coverage.
- `tests/regression/` is split by intent: `analysis/`, `audits/`, `cross_cutting/`, `report/`, and `runtime/`.
- Shared helpers include `conftest.py`, `builders.py`, `_paths.py`, and focused helper modules such as `_report_helpers.py` and scenario helper files when reuse justifies them.

Pi access defaults (prebuilt image)
- Hotspot address: `10.4.0.1`
- HTTP UI and API: `http://10.4.0.1` (port `80` default); if the primary listener is unavailable, try `http://10.4.0.1:8000`
- SSH user: `pi`
- SSH password: `vibesensor`
- Remote simulator quick run: `vibesensor-sim --count 5 --duration 60 --server-host 10.4.0.1 --server-http-port 80 --speed-kmh 0 --no-interactive --no-auto-server`
- Use `--speed-kmh 0` when you only need UDP traffic or the Pi HTTP API is not answering; non-zero speed override performs an HTTP POST before streaming.
- Source: `infra/pi-image/pi-gen/README.md` (values may be overridden at image build time via `VS_FIRST_USER_NAME` and `VS_FIRST_USER_PASS`).

PR monitoring rule
- On every PR update, run the watcher command above; if it exits `RESULT=NON_GREEN`, fix and re-run. Merge only after `RESULT=ALL_GREEN`.

No-cheating and no-backward-compatibility
- Keep code in proper code files, not hidden in docs, JSON, or text wrappers.
- Move newly introduced large inline data to suitable data files when appropriate.
- Breaking changes are allowed. We own the full codebase end to end.
- Do not add or preserve backward-compatibility layers unless explicitly asked. Remove them when encountered.
- Standardize on the current contract, schema, config, and runtime path.
- Do not add new compatibility code just in case. If compatibility seems necessary, flag it explicitly rather than implementing it silently.

# CLAUDE quick guide

Read order + canonical rules
- Read `docs/ai/repo-map.md` first.
- Treat `.github/instructions/general.instructions.md` as canonical shared workflow/validation guidance.
- Apply `.github/instructions/*.md` files only as area-specific deltas.

## Execution loop (medium/large tasks)
- Start with a checklist plan whose item titles include problem + fix + user impact.
- Iterate: `plan → verify existing behavior → root cause → blast radius scan → implement minimal change → targeted tests → broader relevant tests → re-plan`.
- Prefer extending existing logic over parallel implementations.
- Continue autonomously on adjacent in-scope issues.
- Stop only when all items are validated complete, no similar in-scope issues remain, a real blocker exists, or time budget is reached.
- Long deep runs are allowed/preferred for deeper tasks; 45–60 minutes is acceptable.

## Core commands
- Setup: `python -m pip install -e "./apps/server[dev]" && (cd apps/ui && npm ci)`
- Run server (local): `vibesensor-server --config apps/server/config.dev.yaml`
- UI dev/build: `cd apps/ui && npm run dev` / `cd apps/ui && npm run typecheck && npm run build`
- Lint/test/format/smoke: `make lint` / `make test-all` / `make format` / `make smoke`
- PR checks watcher: `python3 tools/ci/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor`

## PR monitoring rule
- Run the PR watcher on every PR update; if it exits `RESULT=NON_GREEN`, fix and re-run.
- Treat `RESULT=ALL_GREEN` as the CI readiness gate before merge.

## Compatibility nuance
- Breaking changes are generally allowed.
- Exception: preserve parsing compatibility for old recorded runs/report data unless explicitly waived.

## Noise control
Avoid scanning these unless explicitly needed, and avoid huge command output unless necessary:
- `artifacts/`
- `infra/pi-image/pi-gen/.cache/`
- `apps/ui/node_modules/`
- `apps/ui/dist/`
- `.venv/`, `.pytest_cache/`, `.ruff_cache/`

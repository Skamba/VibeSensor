Repository overview
- VibeSensor: Python-based data-collection and analysis backend (located in `apps/server/`), a small web UI (`apps/ui/`) built with Node, and device/firmware helpers under `firmware/esp/` and `hardware/`.
- Key runtime artifacts: Docker Compose stack at `docker-compose.yml` and `apps/server/` Python package (`apps/server/pyproject.toml`). PDF report generation lives in `apps/server/vibesensor/report/pdf_builder.py`.

Source-of-truth note
- This file is the canonical short AI guide; `AGENTS.md` and `CLAUDE.md` should remain pointers to this file to prevent drift.

Canonical instruction sources
- Read `docs/ai/repo-map.md` first.
- Shared workflow/validation guardrails live in `.github/instructions/general.instructions.md`.
- Area-specific deltas live in `.github/instructions/{backend,frontend,tests,infra,docs,report}.instructions.md`.

Execution model
- For medium/large tasks, start with an explicit checklist plan whose item titles include problem + fix + user impact.
- Iterate until complete: `plan → verify existing behavior → root cause → blast radius scan → implement minimal change → targeted tests → broader relevant tests → re-plan`.
- Prefer extending/hardening existing logic over parallel implementations.
- Continue autonomously on clearly adjacent in-scope issues.
- Stop only when all plan items are validated complete, no similar in-scope issues remain, a real blocker exists, or time budget is reached.
- Long deep runs are allowed and preferred for deeper tasks; 45–60 minutes is acceptable for medium/large work.

Common commands
- `python -m pip install -e "./apps/server[dev]"`
- `make lint`
- `make test-all`
- `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`
- `python3 tools/ci/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor`
- `cd apps/ui && npm ci && npm run typecheck && npm run build`
- `docker compose build --pull && docker compose up -d`

PR monitoring rule
- On every PR update, run the watcher command above; if it exits `RESULT=NON_GREEN`, fix and re-run. Merge only after `RESULT=ALL_GREEN`.

No-cheating + compatibility
- Keep code in proper code files (not hidden in docs/json/txt wrappers).
- Move newly introduced large inline data to suitable data files (`.json`, `.yaml`, etc.) when appropriate.
- Breaking changes are generally allowed, but preserve parsing compatibility for old recorded runs/report data unless explicitly waived.

Agent operating guide (short)

Read order + canonical rules
- Read `docs/ai/repo-map.md` first.
- Treat `.github/instructions/general.instructions.md` as the canonical shared workflow/validation source.
- Use `.github/instructions/*.md` files for area-specific deltas only.

Execution loop (medium/large tasks)
- Start with an explicit checklist plan (descriptive titles: problem + fix + user impact).
- Iterate until done: `plan → verify existing behavior → root cause → blast radius scan → implement → targeted tests → broader relevant tests → re-plan`.
- Prefer extending existing logic over parallel implementations.
- Continue autonomously on clearly adjacent in-scope issues.
- Stop only when: all items are validated complete, no similar in-scope issues remain, a real blocker exists, or time budget is reached.
- Long deep runs are allowed; 45–60 minutes is acceptable for medium/large tasks when needed.

Setup
- Python: `python -m pip install -e "./apps/server[dev]"`
- UI: `cd apps/ui && npm ci`
- Pi hotspot SSH (default image): host `10.4.0.1`, user `pi`, password `vibesensor`

Validation
- Lint: `make lint`
- CI-aligned tests: `make test-all`
- Optional fast backend tests: `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`
- PR checks watcher (every PR): `python3 tools/ci/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor`
- Backend/frontend changes require Docker validation (`docker compose build --pull`, `docker compose up -d`, simulator run, UI stale-data check).

PR gate
- Use the watcher for every PR update; on `RESULT=NON_GREEN` fix immediately and re-run. Merge only after `RESULT=ALL_GREEN`.

Run server
- Local: `vibesensor-server --config apps/server/config.dev.yaml`

No-cheating + noise control
- Keep code in real code files (not hidden in docs/json/txt wrappers).
- Move newly introduced large inline data to data files (`.json`/`.yaml`) where appropriate.
- Avoid scanning generated/cache/vendor paths unless debugging (`artifacts/`, `.cache/`, `node_modules/`, `dist/`).

Compatibility nuance
- Breaking changes are generally allowed.
- Exception: preserve parsing compatibility for old recorded runs/report data unless explicitly waived by the task.

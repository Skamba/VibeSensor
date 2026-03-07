---
applyTo: "apps/server/**"
---
Backend (python `apps/server/`)
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures backend-specific deltas.
- Backend ownership boundaries:
	- `apps/server/vibesensor/app.py`: FastAPI app factory and CLI-facing startup entry.
	- `apps/server/vibesensor/bootstrap.py`: service wiring and composition root.
	- `apps/server/vibesensor/routes/`: HTTP and WebSocket route groups, assembled by `routes/__init__.py`.
	- `apps/server/vibesensor/runtime/`: runtime coordination, processing loop, and websocket broadcast state.
	- `apps/server/vibesensor/history_db/`: SQLite-backed history and settings persistence.
	- `apps/server/vibesensor/report/pdf_builder.py`: public PDF renderer facade.
	- `apps/server/vibesensor/update/manager.py`: wheel-based updater orchestration.
- Install: `python -m pip install -e "./apps/server[dev]"` (used by CI).
- Backend type gate: `make typecheck-backend` runs the enforced mypy slice for backend runtime/API orchestration.
- Tests: add tests in the matching `tests/<module>/` subdirectory (see `docs/testing.md`); use `tests/integration/` for cross-cutting scenarios and `tests/regression/{analysis,audits,cross_cutting,report,runtime}/` for bug-fix regressions grouped by intent. Prefer `-m "not selenium"` for fast runs. Run a single area with `pytest -q apps/server/tests/<module>/`.
- i18n: Add/modify keys in `apps/server/data/report_i18n.json` when changing user-facing strings.
- Styling/lint: `ruff` is enforced in CI; follow existing `ruff` conventions.
- Documentation maintenance: when backend structure, commands, route ownership, persistence layout, report flow, or update flow changes, update `apps/server/README.md`, `docs/testing.md`, and the relevant `docs/ai/*.md` and `.github/*.instructions.md` files in the same change set.

# Backend agent guidance

Backend-specific rules live in `../../.github/instructions/backend.instructions.md`; test-specific rules live in `tests/AGENTS.md` and `../../.github/instructions/tests.instructions.md`.

Key anchors:
- Package entry points and ownership boundaries: `../../docs/ai/repo-map.md`.
- Domain object rules: `../../docs/domain-model.md`.
- Layering guard: `../../tools/dev/verify_backend_static_guards.py`.

Default validation for backend source changes:
- `make lint`
- `make typecheck-backend`
- `pytest -q apps/server/tests/<module>/`

Add `make sync-contracts` and `make ui-typecheck` when API payloads, generated contracts, or shared backend/frontend constants change.

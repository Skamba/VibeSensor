# Backend agent guidance

- Backend rules: `../../.github/instructions/backend.instructions.md`.
- Updater-specific rules: `../../.github/instructions/backend-updates.instructions.md`.
- Test rules: `tests/AGENTS.md` and `../../.github/instructions/tests.instructions.md`.
- Ownership lookup: `../../docs/ai/repo-map.md`; domain graph: `../../docs/domain-model.md`.
- Layer guard: import-linter contracts in `pyproject.toml` (`lint-imports`, run by `make lint`).
- Default validation: `make lint`, `make typecheck-backend`, and targeted `pytest -q apps/server/tests/<module>/`.
- Add `make sync-contracts` and `make ui-typecheck` for API payloads, generated contracts, or shared backend/frontend constants.

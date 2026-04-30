# Backend test agent guidance

Backend test rules live in `../../../.github/instructions/tests.instructions.md`; the full test map lives in `../../../docs/testing.md`.

Use the matching `apps/server/tests/<module>/` directory for new tests. Reserve `integration/` for cross-cutting regressions and `hygiene/` for guards.

Prefer focused test modules over adding to large omnibus regression files. Test observable behavior instead of source text.

Default focused validation:
- `pytest -q apps/server/tests/<module>/`
- From `apps/server`, run `uv run --python 3.13 --extra dev pytest tests/<module>/ -q` when repo-managed backend dependencies are needed.

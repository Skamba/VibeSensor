# Backend test agent guidance

- Test rules: `../../../.github/instructions/tests.instructions.md`.
- Test map and commands: `../../../docs/testing.md`.
- Put new tests in `apps/server/tests/<package>/`, matching the backend package; reserve `integration/` for cross-cutting regressions and `hygiene/` for guards.
- Prefer focused modules and observable behavior assertions.
- Focused validation: `pytest -q apps/server/tests/<module>/`, or from `apps/server`, `../.venv/bin/python -m pytest tests/<module>/ -q`.

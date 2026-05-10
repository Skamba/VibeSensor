---
applyTo: "apps/server/tests/**"
---
Backend test rules. Use `docs/testing.md` for the concise test map and command router.

- Put new tests in the matching `apps/server/tests/<module>/` directory. Reserve `integration/` for cross-cutting regressions and `hygiene/` for guards.
- Import shared helpers as `from test_support.X import Y`; do not use `from tests.test_support` or mutate `sys.path`.
- Use `test_support/findings.py` factories for finding payloads and `test_support/sample_scenarios.py` for synthetic sample/phase construction. Do not create local duplicates.
- Replace helper re-exports with direct imports unless the helper adds real logic.
- Prefer new focused test modules over adding to large omnibus regression files.
- Test observable behavior, not source strings. Do not use `inspect.getsource` or `ast.parse` on production code in pytest; add needed AST/import guards to `tools/dev/verify_backend_static_guards.py` so `make lint` runs them.
- Do not create per-file fake runtime classes. Use shared `FakeState` from `conftest.py` and customize it via constructor arguments.
- Do not add private production bridge/shim methods solely for test access; test sub-components directly.
- Oversized test/spec guardrails live in `tools/dev/check_hygiene.py`; intentional exceptions belong in `tools/dev/oversized_test_allowlist.yml`.
- Focused validation: `pytest -q apps/server/tests/<module>/` from repo root, or `../.venv/bin/python -m pytest tests/<module>/ -q` from `apps/server` when the repo-managed backend environment must be pinned.

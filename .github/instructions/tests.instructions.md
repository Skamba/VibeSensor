---
applyTo: "apps/server/tests/**"
---
Backend tests (`apps/server/tests/**`)
- Detailed test layout, placement rules, shared root helpers, and CI command usage live in `docs/testing.md`; this file only captures test-specific deltas, so use the matching `tests/<module>/` directory from that map, reserve `integration/` for cross-cutting regressions, and use `hygiene/` for guards.
- Import style: use `from test_support.X import Y` (short form). The `tests/` directory is on `sys.path` via `testpaths` in `pyproject.toml`. Do not use `from tests.test_support` or manipulate `sys.path` for test imports.
- Use `test_support/findings.py` factories (`make_finding_payload`, `make_ref_finding`, `make_info_finding`) for constructing finding dicts in tests. Do not create local finding factories in individual test files.
- Test helper re-exports that only alias another module's symbol should be replaced with direct imports. Keep test helper modules for functions that add real logic.
- Use `test_support/sample_scenarios.py` builders as the single source for synthetic sample/phase construction. Do not duplicate sample-generation logic in other helpers.
- Do not add new tests to existing large omnibus regression files — prefer a new focused test module in the matching feature-area directory.
- Do not use `inspect.getsource` or `ast.parse` on production code in tests. These create brittle source-string-matching assertions that break on any refactor. Instead, test the observable behavior: call the function with representative inputs and assert on outputs, side-effects, or raised exceptions. If you need an AST/import guard, add it to `tools/dev/verify_backend_static_guards.py` so it runs under `make lint` instead of pytest.
- Do not create local `FakeState` or fake runtime classes in individual test files. Use the shared `FakeState` from `conftest.py` and customise it via constructor arguments.
- Do not add private bridge/shim methods to production classes solely for test access. Test sub-components directly (e.g. `proc._store._get_or_create_unlocked`, `proc._metrics.fft_params`) instead of adding pass-through wrappers on the outer class.
- Oversized test/spec guardrails live in `tools/dev/check_hygiene.py` with the explicit allowlist at `tools/dev/oversized_test_allowlist.yml`; split oversized files by default, and only add an allowlist entry when the file is intentionally large and the reason is documented there.
- Optional focused backend pytest run (for faster iteration, not a CI substitute): run `pytest -q apps/server/tests/<module>/` from the repo root, or `../.venv/bin/python -m pytest tests/<module>/ -q` from `apps/server` when you need to pin the repo-managed backend environment.

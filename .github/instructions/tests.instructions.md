---
applyTo: "apps/server/tests/**"
---
Tests
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures test-specific deltas.
- Test layout: feature-based subdirectories under `apps/server/tests/` mirror source modules. See `docs/testing.md` for the full map.
- Mapping rule: if you change `vibesensor/<module>/`, the tests live in `tests/<module>/`.
- Cross-cutting directories: `integration/` (scenarios and cross-cutting regressions), `hygiene/` (guards), `e2e/` (browser).
- Shared helpers: `conftest.py` (fixtures, available to all subdirs), `_paths.py` (use `SERVER_ROOT`/`REPO_ROOT` instead of `Path(__file__).parents[N]`), and the focused `test_support/` modules for synthetic data generators and assertions.
- Test helper re-exports that only alias another module's symbol should be replaced with direct imports. Keep test helper modules for functions that add real logic.
- Use `test_support/sample_scenarios.py` builders as the single source for synthetic sample/phase construction. Do not duplicate sample-generation logic in other helpers.
- New tests: place in the matching `tests/<module>/` subdirectory; use `tests/integration/` for cross-cutting scenarios and multi-subsystem regressions.
- When an intentional refactor changes function-level seams or helper boundaries, update or replace tightly coupled tests so they validate current behavior and contracts instead of preserving obsolete internals.
- Do not use `inspect.getsource` or `ast.parse` on production code in tests. These create brittle source-string-matching assertions that break on any refactor. Instead, test the observable behavior: call the function with representative inputs and assert on outputs, side-effects, or raised exceptions.
- Default CI-aligned test suite: `make test-all` (runs `python3 tools/tests/run_ci_parallel.py` to mirror CI `backend-quality`, `backend-typecheck`, `frontend-typecheck`, `ui-smoke`, `backend-tests`, and `e2e` job groups in parallel).
- Optional CI job subset for faster local iteration: `python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests`.
- Run a single feature area: `pytest -q apps/server/tests/analysis/` (or any subdirectory).
- Optional focused backend pytest run (for faster iteration, not a CI substitute): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.

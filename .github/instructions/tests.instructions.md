---
applyTo: "apps/server/tests/**"
---
Tests
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures test-specific deltas.
- Test layout: feature-based subdirectories under `apps/server/tests/` mirror source modules. See `docs/testing.md` for the full map.
- Mapping rule: if you change `vibesensor/<module>/`, the tests live in `tests/<module>/`.
- Cross-cutting directories: `integration/` (scenarios), `regression/` (bug fixes), `hygiene/` (guards), `e2e/` (browser).
- Shared helpers: `conftest.py` (fixtures, available to all subdirs), `builders.py` (synthetic data generators), `_paths.py` (use `SERVER_ROOT`/`REPO_ROOT` instead of `Path(__file__).parents[N]`).
- New tests: place in the matching `tests/<module>/` subdirectory; use `tests/integration/` for cross-cutting scenarios, `tests/regression/` for bug-fix regressions.
- Default CI-aligned test suite: `make test-all` (runs `python3 tools/tests/run_ci_parallel.py` to mirror CI `preflight`, `tests`, and `e2e` job groups in parallel).
- Optional CI job subset for faster local iteration: `python3 tools/tests/run_ci_parallel.py --job preflight --job tests`.
- Run a single feature area: `pytest -q apps/server/tests/analysis/` (or any subdirectory).
- Optional focused backend pytest run (for faster iteration, not a CI substitute): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.

---
applyTo: "apps/server/tests/**"
---
Tests
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures test-specific deltas.
- Default CI-aligned test suite: `make test-all` (runs `python3 tools/tests/run_ci_parallel.py` to mirror CI `preflight`, `tests`, and `e2e` job groups in parallel).
- Optional CI job subset for faster local iteration: `python3 tools/tests/run_ci_parallel.py --job preflight --job tests`.
- Optional focused backend pytest run (for faster iteration, not a CI substitute): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.
- New backend features should include focused unit tests under `apps/server/tests/`; larger/breaking changes can include broader integration coverage when useful.

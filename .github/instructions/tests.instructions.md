---
applyTo: "apps/server/tests/**"
---
Tests
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures test-specific deltas.
- Default CI-aligned test suite: `make test-all` (runs `python3 tools/tests/run_full_suite.py`).
- Optional focused backend pytest run (for faster iteration, not a CI substitute): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.
- New backend features should include focused unit tests under `apps/server/tests/`; larger/breaking changes can include broader integration coverage when useful.

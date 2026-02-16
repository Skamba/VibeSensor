---
applyTo: "pi/tests/**"
---
Tests
- Fast tests: `pytest -q -m "not selenium" pi/tests` (used in CI).
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.
- New backend features should include focused unit tests under `pi/tests/` and avoid heavy integration tests in quick PRs.

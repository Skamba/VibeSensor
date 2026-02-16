Agent operating rules
- How to explore the repo efficiently:
  - Start at `pi/` for backend entry points and `ui/` for frontend. Follow imports from `pi/vibesensor/__init__.py` and `pi/vibesensor/app.py`.
  - Use `pi/tests/` to see expected behaviour and fixtures; tests are the fastest way to understand runtime contracts.
  - Search `.github/workflows/ci.yml` and `pi/pyproject.toml` for build, lint and test commands.

- How to make changes:
  - Make small commits with focused intent. Prefer a single logical change per commit.
  - Do not perform large, sweeping refactors in a single PR.
  - Update or add tests in `pi/tests/` covering new behaviour.

- How to validate changes without running code:
  - Use static checks: run `ruff` locally and inspect `pyproject.toml` for dependency changes.
  - Read `pi/tests/` to confirm expected I/O and error cases; add/adjust assertions as necessary.

- Misc rules:
  - Never add secrets to the repository. Use `pi/wifi-secrets.example.env` as a template for device configuration.
  - When altering report text, update `pi/vibesensor/report_i18n.py`.

---
applyTo: "docker-compose.yml,.github/workflows/**"
---
Infra / Docker / CI
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures infra-specific deltas.
- Local dev: `docker compose build --pull` then `docker compose up -d`.
- CI: `.github/workflows/ci.yml` is authoritative for job commands (`preflight`, `tests`, `e2e`).
- Local CI-parity run: `make test-all` (runs `python3 tools/tests/run_ci_parallel.py`, which mirrors those CI job command groups in parallel).
- Keep CI steps maintainable; larger CI/workflow updates are allowed when needed. If adding new test dependencies, update `apps/server/pyproject.toml` so CI installs them via the editable install.
- Avoid embedding secrets in workflow files; use repository secrets for tokens.

---
applyTo: "docker-compose.yml,.github/workflows/**"
---
Infra / Docker / CI
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures infra-specific deltas.
- Local dev: `docker compose build --pull` then `docker compose up -d`.
- CI: `.github/workflows/ci.yml` shows steps used in CI (setup Python/Node, pip install -e "./apps/server[dev]", ruff, UI checks, and `make test-all`).
- Keep CI steps maintainable; larger CI/workflow updates are allowed when needed. If adding new test dependencies, update `apps/server/pyproject.toml` so CI installs them via the editable install.
- Avoid embedding secrets in workflow files; use repository secrets for tokens.

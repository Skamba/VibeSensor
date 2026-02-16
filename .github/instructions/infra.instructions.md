---
applyTo: "docker-compose.yml,.github/workflows/**"
---
Infra / Docker / CI
- Local dev: `docker compose build --pull` then `docker compose up -d`.
- CI: `.github/workflows/ci.yml` shows steps used in CI (setup Python/Node, pip install -e "./pi[dev]", ruff, pytest, UI build).
- Keep CI steps small; if adding new test dependencies, update `pi/pyproject.toml` so CI installs them via the editable install.
- Avoid embedding secrets in workflow files; use repository secrets for tokens.

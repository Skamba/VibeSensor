---
applyTo: "ui/**"
---
Frontend (ui)
- Commands: `cd ui && npm ci`, `cd ui && npm run build`, `cd ui && npm run typecheck`.
- Keep frontend changes scoped and update `ui/nginx.conf` only if static paths change.
- Prefer updating `ui/src/` components and running `npm run build` locally before pushing.
- After UI changes, always rebuild and test via the Docker container (`docker compose build --pull && docker compose up -d`). Use the simulator to send test data and verify the UI renders correctly, including that stale data is not displayed after sensors disconnect.

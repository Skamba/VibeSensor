---
applyTo: "ui/**"
---
Frontend (ui)
- Commands: `cd ui && npm ci`, `cd ui && npm run build`, `cd ui && npm run typecheck`.
- Keep frontend changes scoped and update `ui/nginx.conf` only if static paths change.
- Prefer updating `ui/src/` components and running `npm run build` locally before pushing.

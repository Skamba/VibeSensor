---
applyTo: "apps/ui/**"
---
Frontend (`apps/ui`)
- Commands: `cd apps/ui && npm ci`, `cd apps/ui && npm run build`, `cd apps/ui && npm run typecheck`.
- Keep frontend changes focused when practical; larger cross-cutting and breaking UI changes are allowed.
- Keep `apps/ui/src/` free of `any`/`as any`; prefer explicit interfaces, unions, and narrowing helpers when wiring server payloads and DOM state.
- Prefer updating `apps/ui/src/` components and running `npm run build` locally before pushing.

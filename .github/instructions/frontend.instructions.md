---
applyTo: "apps/ui/**"
---
Frontend (`apps/ui`)
- Commands: `cd apps/ui && npm ci`, `cd apps/ui && npm run build`, `cd apps/ui && npm run typecheck`.
- Shared contract sync is canonicalized through `npm run sync:contracts` (which calls `tools/config/sync_shared_contracts_to_ui.mjs` for both shared TS constants and generated HTTP API contracts); do not introduce a second sync path.
- Keep frontend changes focused when practical; larger cross-cutting and breaking UI changes are allowed.
- Keep `apps/ui/src/` free of `any`/`as any`; prefer explicit interfaces, unions, and narrowing helpers when wiring server payloads and DOM state.
- For server/WebSocket inputs, keep raw data as `unknown` until a decoder proves the shape; avoid treating inbound payloads as generic record bags up front.
- Prefer updating `apps/ui/src/` components and running `npm run build` locally before pushing.

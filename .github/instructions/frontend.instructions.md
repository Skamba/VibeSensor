---
applyTo: "apps/ui/**"
---
Frontend (`apps/ui`)
- Shared contract-sync authority lives in `apps/ui/README.md` § "Contract sync"; follow that flow and do not introduce a second sync path.
- Keep frontend changes focused when practical; larger cross-cutting and breaking UI changes are allowed.
- Keep `apps/ui/src/` free of `any`/`as any`; prefer explicit interfaces, unions, and narrowing helpers when wiring server payloads and DOM state.
- For server/WebSocket inputs, keep raw data as `unknown` until a decoder proves the shape; avoid treating inbound payloads as generic record bags up front.

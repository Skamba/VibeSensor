---
applyTo: "apps/ui/**"
---
Frontend (`apps/ui`)
- Shared contract-sync authority lives in `apps/ui/README.md` § "Contract sync"; follow that flow and do not introduce a second sync path.
- Keep frontend changes focused when practical; larger cross-cutting and breaking UI changes are allowed.
- `apps/ui/src/app/runtime/` owns app-wide composition, startup, shell chrome, live transport, spectrum lifecycle, and other long-lived controllers. Keep cross-feature orchestration there instead of re-creating it inside feature modules.
- `apps/ui/src/app/features/` owns feature workflows, API calls, polling lifecycles, and app-state mutations for settings, realtime, history, updates, cars, and ESP flash. Extend the existing feature owner before adding a parallel controller/service for the same surface.
- `apps/ui/src/app/views/` owns DOM rendering, HTML helpers, and event-target decoding. Keep views data-in / DOM-out; do not move request orchestration, polling, or business branching into view modules.
- Keep DOM rendering and event decoding in views, while runtime/feature modules translate those events into workflow actions.
- Keep polling, timers, WebSocket/session state, and other shared runtime state centralized. Reuse `app/features/polling_controller.ts`, `app/runtime/ui_live_transport_controller.ts`, and `app/ui_app_state.ts` instead of introducing duplicate per-feature loops or freshness owners.
- Avoid parallel fetch, poll, or contract-sync paths when one canonical path already exists. Reuse `api/http.ts`, `ws.ts`, generated contracts, `ws_payload_validator.ts`, and `server_payload.ts` instead of adding alternate transport wrappers or ad-hoc payload adapters for the same server state.
- Keep `apps/ui/src/` free of `any`/`as any`; prefer explicit interfaces, unions, and narrowing helpers when wiring server payloads and DOM state.
- For server/WebSocket inputs, keep raw data as `unknown` until a decoder proves the shape; prefer generated contracts, schema-backed validation, and narrow adapters over loose record-bag handling.
- Validation: for frontend logic, contract, or composition changes, run `cd apps/ui && npm run typecheck && npm run build`. Add `cd apps/ui && npm run test:visual` when rendered UI states or snapshots change, and reserve the local Docker stack for material UI/backend runtime integration changes.

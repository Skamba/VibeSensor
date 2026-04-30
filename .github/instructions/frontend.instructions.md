---
applyTo: "apps/ui/**"
---
Frontend (`apps/ui`)
- Shared contract-sync authority lives in `apps/ui/README.md` § "Contract sync"; follow that flow and do not introduce a second sync path.
- Keep frontend changes focused when practical; larger cross-cutting and breaking UI changes are allowed.
- `apps/ui/src/app/runtime/` owns app-wide composition, startup, shell chrome, live transport, spectrum lifecycle, and other long-lived controllers. Keep cross-feature orchestration there instead of re-creating it inside feature modules.
- `apps/ui/src/app/features/` owns feature workflows, API calls, polling lifecycles, and app-state mutations for settings, realtime, history, updates, cars, and ESP flash. Extend the existing feature owner before adding a parallel controller/service for the same surface.
- `apps/ui/src/app/views/` owns DOM rendering, HTML helpers, and event-target decoding. Keep views data-in / DOM-out; do not move request orchestration, polling, or business branching into view modules.
- Keep computed/derived ownership out of view components when possible. Prefer runtime, feature, presenter, or shared adapter modules to own `computed()` state, and let views mostly read already-derived signal values.
- Keep DOM rendering and event decoding in views, while runtime/feature modules translate those events into workflow actions.
- Keep polling, timers, WebSocket/session state, and other shared runtime state centralized. Reuse the feature workflow polling seams, `apps/ui/src/app/runtime/ui_live_transport_controller.ts`, and `apps/ui/src/app/ui_app_state.ts` instead of introducing duplicate per-feature loops or freshness owners.
- Avoid parallel fetch, poll, or contract-sync paths when one canonical path already exists. Reuse `apps/ui/src/api/http.ts`, `apps/ui/src/ws.ts`, generated contracts, `apps/ui/src/ws_payload_validator.ts`, and `apps/ui/src/server_payload.ts` instead of adding alternate transport wrappers or ad-hoc payload adapters for the same server state.
- For owned server-controlled runtime boundaries, validate `unknown` payloads once at the API/transport seam with Valibot (or a documented hot-path custom validator) before feature/runtime code consumes typed data.
- Keep `apps/ui/src/` free of `any`/`as any`; prefer explicit interfaces, unions, and narrowing helpers when wiring server payloads and DOM state.
- For server/WebSocket inputs, keep raw data as `unknown` until a decoder proves the shape; prefer generated contracts, schema-backed validation, and narrow adapters over loose record-bag handling.
- Validation: for frontend logic, contract, or composition changes, run `cd apps/ui && npm run typecheck && npm run build`. Add `cd apps/ui && npm run test:visual` when rendered UI states or snapshots change, and reserve the local Docker stack for material UI/backend runtime integration changes.

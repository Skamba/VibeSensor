---
applyTo: "apps/ui/**"
---
Frontend rules for `apps/ui`.

- Contract sync authority is `apps/ui/README.md` "Contract sync". Do not add a second sync path or hand-written API contract drift.
- `src/app/runtime/` owns app-wide composition, startup, shell chrome, live transport, spectrum lifecycle, and long-lived controllers.
- `src/app/features/` owns feature workflows, API calls, polling lifecycles, and app-state mutations for settings, realtime, history, updates, cars, and ESP flash.
- `src/app/views/` owns DOM rendering, HTML helpers, and event-target decoding. Keep views data-in/DOM-out; runtime/feature modules translate events into workflow actions.
- Keep computed/derived state outside views when practical; use runtime, feature, presenter, or shared adapter owners.
- Centralize polling, timers, WebSocket/session state, and freshness. Reuse existing feature polling seams, `src/app/runtime/ui_live_transport_controller.ts`, and `src/app/ui_app_state.ts`.
- Avoid parallel fetch, poll, transport, validation, or contract-sync paths. Reuse `src/api/http.ts`, `src/ws.ts`, generated contracts, `src/ws_payload_validator.ts`, and `src/server_payload.ts`.
- Keep server/WebSocket inputs as `unknown` until Valibot, generated contracts, schema-backed validation, or a documented hot-path validator proves the shape.
- Keep `src/` free of `any`/`as any`; prefer interfaces, unions, and narrowing helpers.
- Validation: start with `make plan-validation`; run `make ui-typecheck` for frontend logic/contracts/composition. Add `cd apps/ui && npm run build` for bundle behavior, `npm run test:unit` for feature/runtime logic, and `npm run test:visual` for rendered UI or snapshots.

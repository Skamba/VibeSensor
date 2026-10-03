---
applyTo: "apps/ui/**"
---
Frontend rules for `apps/ui`.

- Contract sync authority is `apps/ui/README.md` "Contract sync". Do not add a second sync path or hand-written API contract drift.
- `src/main.tsx` renders the single Preact root; `src/app.tsx` is the shell (navigation, preferences, status pills, error banner, confirmation dialog, view and settings-tab switching) and `src/app_store.ts` owns shell state.
- New and rewritten pages live in `src/pages/<page>/`: `<Page>.tsx`, a small `<page>_store.ts` (signals, polling, API calls), and pure helper modules with unit tests. Pages never import other pages (dependency-cruiser); share code through `src/` modules outside `pages/`.
- The live transport and spectrum still use `src/app/runtime/` controllers and `src/app/views/` panels wired in `src/app/feature_wiring.ts`; move them out wholesale instead of extending that wiring. Live data shared across pages lives in `src/live_store.ts`.
- Translate with `t()` from `src/i18n.ts` (no inline English fallbacks); the Dutch catalog loads lazily.
- Keep computed/derived state outside views when practical; use runtime, feature, presenter, or shared adapter owners.
- Centralize polling, timers, WebSocket/session state, and freshness. Reuse existing feature polling seams, `src/app/runtime/ui_live_transport_controller.ts`, and `src/app/ui_app_state.ts`.
- Avoid parallel fetch, poll, transport, validation, or contract-sync paths. Reuse `src/api/http.ts`, `src/ws.ts`, generated contracts, `src/ws_payload_validator.ts`, and `src/server_payload.ts`.
- Keep server/WebSocket inputs as `unknown` until Valibot, generated contracts, schema-backed validation, or a documented hot-path validator proves the shape.
- Keep `src/` free of `any`/`as any`; prefer interfaces, unions, and narrowing helpers.
- Validation: run `make ui-typecheck` for frontend logic/contracts/composition. Add `cd apps/ui && npm run build` for bundle behavior, `npm run test:unit` for feature/runtime logic, and `npm run test:smoke` for critical rendered UI journeys.

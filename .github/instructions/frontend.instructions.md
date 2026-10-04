---
applyTo: "apps/ui/**"
---
Frontend rules for `apps/ui`.

- Contract sync authority is `apps/ui/README.md` "Contract sync". Do not add a second sync path or hand-written API contract drift.
- `src/main.tsx` renders the single Preact root; `src/app.tsx` is the shell (navigation, preferences, status pills, error banner, confirmation dialog, view and settings-tab switching) and `src/app_store.ts` owns shell state.
- Pages live in `src/pages/<page>/`: `<Page>.tsx`, a small `<page>_store.ts` (signals, polling, API calls), and pure helper modules with unit tests. Pages never import other pages (`tests/page_boundaries.spec.ts`); share code through `src/` modules outside `pages/` (`app_store.ts`, `settings_store.ts`, `live_store.ts`) and let the shell compose pages.
- Translate with `t()` from `src/i18n.ts` (no inline English fallbacks); the Dutch catalog loads lazily.
- Show speeds (the API sends km/h) with `formatSpeed`/`formatSpeedRange` from `src/format.ts` and the shell's `speedUnit` signal, not a hard-coded `km/h`. Only the manual-speed input on Speed Source is entered in km/h.
- Keep derived state in store `computed()`s or pure model functions, not in components.
- Centralize polling, timers, WebSocket/session state, and freshness: poll with `src/poll.ts`; live data flows `src/ws.ts` → `src/live_transport.ts` → `src/live_store.ts`.
- Avoid parallel fetch, poll, transport, validation, or contract-sync paths. Reuse `src/api/http.ts`, `src/ws.ts`, generated contracts, `src/ws_payload_validator.ts`, and `src/server_payload.ts`.
- Keep server/WebSocket inputs as `unknown` until Valibot, generated contracts, schema-backed validation, or a documented hot-path validator proves the shape.
- Keep `src/` free of `any`/`as any`; prefer interfaces, unions, and narrowing helpers.
- Car wizard, speed source, readiness, and History wording: check the principles in `docs/user_journeys.md` and update `docs/user_journey_gaps.md` when you close a gap.
- Validation: run `make ui-typecheck` for frontend logic/contracts/composition. Add `cd apps/ui && npm run build` for bundle behavior, `npm run test:unit` for pure logic, and `npm run test:smoke` for the per-page journeys.

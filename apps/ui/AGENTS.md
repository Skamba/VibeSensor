# Frontend agent guidance

- Frontend rules: `../../.github/instructions/frontend.instructions.md`.
- Contract sync: `README.md` "Contract sync".
- Owners: `src/app.tsx` + `src/app_store.ts` for the shell (one render root, navigation, banner, confirmation, preferences); `src/pages/<page>/` for page components, stores, and pure helpers (pages never import other pages); `src/live_store.ts` + `src/live_transport.ts` for live data and the WebSocket; `src/settings_store.ts` for cars and speed source.
- Validation: `make ui-typecheck`; add `cd apps/ui && npm run build` for bundle behavior and `cd apps/ui && npm run test:smoke` for the per-page Playwright journeys.

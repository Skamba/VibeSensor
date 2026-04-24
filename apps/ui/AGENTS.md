# Frontend agent guidance

Frontend-specific rules live in `../../.github/instructions/frontend.instructions.md`.

Key anchors:
- Contract sync: `README.md` section "Contract sync".
- Runtime composition: `src/app/runtime/`.
- Feature workflows and API/polling state: `src/app/features/`.
- DOM rendering and event decoding: `src/app/views/`.

Default validation for frontend logic, contracts, or composition:
- `make ui-typecheck`
- `cd apps/ui && npm ci && npm run build` when bundle behavior matters.

Add `cd apps/ui && npm run test:visual` when rendered UI states or snapshots change.

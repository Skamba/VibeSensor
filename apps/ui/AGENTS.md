# Frontend agent guidance

- Frontend rules: `../../.github/instructions/frontend.instructions.md`.
- Contract sync: `README.md` "Contract sync".
- Owners: `src/app/runtime/` for composition/controllers, `src/app/features/` for workflows/API/polling, `src/app/views/` for DOM/event decoding.
- Validation: `make ui-typecheck`; add `cd apps/ui && npm run build` for bundle behavior and `cd apps/ui && npm run test:visual` for rendered UI/snapshots.

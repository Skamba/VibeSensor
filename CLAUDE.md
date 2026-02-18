# CLAUDE quick guide

Use `docs/ai/repo-map.md` first, then read only the minimal files needed.

## Core commands
- Setup: `python -m pip install -e "./apps/server[dev]" && (cd apps/ui && npm ci)`
- Run server (local): `python -m vibesensor.app --config apps/server/config.dev.yaml`
- Build Pi image: `./infra/pi-image/pi-gen/build.sh`
- Firmware build/flash: `cd firmware/esp && pio run -t upload`
- UI dev/build: `cd apps/ui && npm run dev` / `cd apps/ui && npm run typecheck && npm run build`
- Lint/test/format/smoke: `make lint` / `make test` / `make format` / `make smoke`

## Invariants
- Shared contracts in `libs/shared/contracts` are canonical.
- `libs/core` stays pure (no network/db/filesystem/framework imports).
- `apps/server` composes adapters + core.
- Prefer `apps/*`, `libs/*`, `infra/*` paths over legacy compatibility links.

## Noise control
Avoid scanning these unless explicitly needed:
- `artifacts/`
- `infra/pi-image/pi-gen/.cache/`
- `apps/ui/node_modules/`
- `apps/ui/dist/`
- `.venv/`, `.pytest_cache/`, `.ruff_cache/`

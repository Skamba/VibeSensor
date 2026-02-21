# CLAUDE quick guide

Use `docs/ai/repo-map.md` first, then read the files needed for the task (including larger cross-cutting changes when required).

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
- Backward compatibility is never a requirement; breaking/larger changes are allowed when intentional.

## AI PR checklist — UI changes
When opening a PR that touches `apps/ui/`:
1. Build: `cd apps/ui && npm run build`
2. Take a screenshot and verify graph data (fails non-zero if chart is empty):
   ```
   cd apps/ui && npm run screenshot -- /tmp/vibesensor-pr-screenshot.png
   ```
3. Commit the screenshot to the branch so it travels with the PR:
   ```
   cp /tmp/vibesensor-pr-screenshot.png docs/screenshots/latest-live-view.png
   git add docs/screenshots/latest-live-view.png
   git commit -m "chore: update UI screenshot"
   git push -u origin <branch>
   ```
4. Reference it in the PR body (replace BRANCH with the actual branch name):
   ```
   ![Live view screenshot](https://raw.githubusercontent.com/Skamba/VibeSensor/<BRANCH>/docs/screenshots/latest-live-view.png)
   ```
5. Regenerate snapshots if chart or layout changed: `cd apps/ui && npm run snapshot:update`

## Noise control
Avoid scanning these unless explicitly needed:
- `artifacts/`
- `infra/pi-image/pi-gen/.cache/`
- `apps/ui/node_modules/`
- `apps/ui/dist/`
- `.venv/`, `.pytest_cache/`, `.ruff_cache/`

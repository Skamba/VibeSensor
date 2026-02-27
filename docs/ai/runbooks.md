# AI Runbooks (Low-Noise)

## Setup (minimal)
```bash
python -m pip install -e "./apps/server[dev]"
cd apps/ui && npm ci
```

## Run backend + simulator
```bash
vibesensor-server --config apps/server/config.dev.yaml
# in another shell
vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
```

## Fast check (quiet)
```bash
scripts/ai/task ai:check
# or
make ai-check
```

## Targeted tests
```bash
# pass pytest args after --
scripts/ai/task ai:test -- apps/server/tests/test_config.py -k self_heal -q
# or
make ai-test
# or quicker backend loop with progress output
make test-fast
```

## Minimal smoke
```bash
scripts/ai/task ai:smoke
# or
make ai-smoke
```

## CI-parity suite (parallel)
```bash
make test-all
# or select CI job groups
python3 tools/tests/run_ci_parallel.py --job preflight --job tests
```

## Updater incident runbook (wheel-first)

- Default updater model is wheel-based (`vibesensor/update_manager.py` installs release wheels).
- Do not use direct runtime file patching as normal delivery.
- Emergency-only path: if updater itself is broken on a live Pi, apply a temporary in-place patch to restore service.
- Mandatory follow-up after emergency patching:
  1. same fix in repo,
  2. targeted tests + lint,
  3. PR to green + merge,
  4. rerun updater on device and confirm success (`state=success`) so device returns to wheel-managed state.

## Context bundle
```bash
scripts/ai/task ai:pack
# or
make ai-pack
```

## Scoped triage
```bash
scripts/ai/triage apps/server/vibesensor --symbol clients_with_recent_data
```

## Debug with scoped output
- Keep noisy command output in files under `artifacts/ai/logs/`.
- Prefer scoped grep:
  - `rg "self_heal" -g"*.py" apps/server/vibesensor/`
  - `rg "vibesensor-hotspot" -g"*.service" apps/server/systemd/ infra/pi-image/pi-gen/assets/`
- Avoid repo-wide unbounded scans.

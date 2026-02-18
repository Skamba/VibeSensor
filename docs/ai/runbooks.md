# AI Runbooks (Low-Noise)

## Setup (minimal)
```bash
python -m pip install -e "./apps/server[dev]"
cd apps/ui && npm ci
```

## Run backend + simulator
```bash
python -m vibesensor.app --config apps/server/config.dev.yaml
# in another shell
python apps/simulator/sim_sender.py --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
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
```

## Minimal smoke
```bash
scripts/ai/task ai:smoke
# or
make ai-smoke
```

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

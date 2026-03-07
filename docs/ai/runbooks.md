# AI Runbooks

## Setup

```bash
python3 -m pip install -e "./apps/server[dev]"
cd apps/ui && npm ci
```

## Run the local stack

Backend:

```bash
vibesensor-server --config apps/server/config.dev.yaml
```

UI dev server:

```bash
cd apps/ui && npm run dev
```

Simulator:

```bash
vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
```

Check `http://127.0.0.1` first. If the active config is using the development port, use `http://127.0.0.1:8000`.

## Run against a Pi

```bash
curl -sf http://10.4.0.1/api/clients || curl -sf http://10.4.0.1:8000/api/clients

vibesensor-sim \
  --count 5 \
  --duration 60 \
  --server-host 10.4.0.1 \
  --server-http-port 80 \
  --speed-kmh 0 \
  --no-interactive \
  --no-auto-server
```

Use `--server-http-port 8000` only when the primary listener on port `80` is unavailable.

## Fast local checks

```bash
make lint
make typecheck-backend
make ui-typecheck
make ai-check
make ai-test
make ai-smoke
make docs-lint
```

For focused backend tests:

```bash
python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests
pytest -q apps/server/tests/report/
pytest -q apps/server/tests/regression/runtime/
```

## CI-parity runs

```bash
make test-all
python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests
python3 tools/tests/run_ci_parallel.py --job frontend-typecheck --job ui-smoke
```

Required merge gates are now explicit: backend quality, backend type check, frontend type check, backend tests, UI smoke, and e2e.

## Documentation drift check

After any meaningful code change:

1. Re-read the touched ownership boundary.
2. Check whether `docs/testing.md`, `docs/ai/*.md`, the relevant README, and the relevant instruction files still match the live code.
3. Update stale docs in the same change set.

Do not defer doc cleanup unless the user explicitly asks for code-only work.

## Updater incident runbook

- Default updater model is wheel-based and lives in `apps/server/vibesensor/update/`, with `manager.py` as the public facade over the workflow and subsystem modules.
- Do not use direct runtime file patching as normal delivery.
- Emergency-only path: if the updater itself is broken on a live Pi, apply a temporary in-place patch to restore service.
- Mandatory follow-up after emergency patching:
  1. same fix in repo,
  2. targeted tests plus lint,
  3. PR to green plus merge,
  4. rerun updater on the device and confirm success so the Pi returns to wheel-managed state.

## Context bundle and triage

```bash
make ai-pack
scripts/ai/triage apps/server/vibesensor --symbol clients_with_recent_data
```

## Low-noise debugging

- Keep noisy command output in `artifacts/ai/logs/`.
- Prefer scoped `rg` searches over repo-wide scans.
- Start with the owning package and its nearest tests before expanding outward.

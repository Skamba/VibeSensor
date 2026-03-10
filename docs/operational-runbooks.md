# Operational Runbooks

This file is the human-facing operational guide for common VibeSensor incidents and release checks. Developer quick commands live in [.github/copilot-instructions.md](../.github/copilot-instructions.md).

## Quick health checks

Local or Docker-backed stack:

```bash
docker compose ps
curl -sf http://127.0.0.1/api/health || curl -sf http://127.0.0.1:8000/api/health
```

Pi hotspot path:

```bash
curl -sf http://10.4.0.1/api/health || curl -sf http://10.4.0.1:8000/api/health
curl -sf http://10.4.0.1/api/clients || curl -sf http://10.4.0.1:8000/api/clients
```

When interpreting `/api/health`, check `startup_state`, `startup_phase`, and
`background_task_failures` before chasing downstream symptoms. A healthy boot
should reach `startup_state: ready` with an empty `background_task_failures`
map. The response also includes operational metrics:

- `startup_warnings` — precondition issues detected at boot (e.g. low disk space)
- `tick_duration_s` / `max_tick_duration_s` / `tick_count` — processing loop timing
- `db_last_write_duration_s` / `db_max_write_duration_s` — DB write latency

## Diagnose high dropped frames

1. Confirm the health endpoint responds and inspect connected clients.
2. Check whether the simulator or live devices reproduce the drop pattern consistently.
3. Reduce Wi-Fi contention and confirm the Pi hotspot channel and proximity are reasonable.
4. If the problem is local-only, inspect Docker logs:

```bash
docker compose logs --tail 100
```

5. If the issue is on a Pi, also review systemd or journal output for the service and hotspot helpers.

## Diagnose stale or missing live updates

1. Verify `/api/health` and `/api/clients` still respond.
2. Confirm WebSocket access with the smoke tool:

```bash
vibesensor-ws-smoke --uri ws://127.0.0.1:8000/ws --min-clients 1 --timeout 20
```

3. Reproduce with the simulator to separate data-ingest issues from UI-only issues:

```bash
vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
```

4. If health is good but the UI is stale, check browser console and recent frontend builds.

## Update and rollback checks

1. Confirm current runtime and update status from the UI or update endpoints.
2. Before shipping a release, ensure the release workflow builds the wheel and passes the smoke validation step.
3. If an update fails on-device, do not assume rollback succeeded silently. Confirm service health after the attempt and check updater issues for rollback wheel validation failures.
4. The updater now aborts before touching the live environment if it cannot write a fresh rollback snapshot or cannot verify free disk space for the rollback area. Treat either condition as an infrastructure problem to fix first, not a retry-until-it-works event.
5. If rollback metadata is missing, the updater will only trust the newest rollback wheel after structural archive validation; if checksum metadata exists, a mismatch should be treated as a broken rollback snapshot, not a transient install failure.
6. The Update panel now shows operational health from `/api/health`; use its degradation reasons, data-loss counts, and persistence status as the first operator-facing signal before digging through logs. Key degradation reasons include `persistence_write_error` (DB write failures), `persistence_samples_dropped` (samples lost during recording), and `last_analysis_failed` (most recent post-analysis run errored). The health response also exposes `samples_written`, `samples_dropped`, `last_completed_run_id`, and `last_completed_run_error` in its persistence section for detailed diagnostics.
7. If emergency patching was used to restore service, follow up with the repo fix, validation, and a successful updater rerun so the device returns to wheel-managed state.

## Local release readiness

Run these before treating a branch as release-ready:

```bash
make lint
make typecheck-backend
make ui-typecheck
make coverage
make test-all
docker compose build --pull
docker compose up -d
docker compose ps
vibesensor-sim --count 5 --duration 10 --no-interactive
```

If the stack does not serve on port `80`, use `http://127.0.0.1:8000` as the dev fallback.

## CI failure triage

When a PR check fails:

1. Reproduce the failing job locally with the matching `run_ci_parallel.py` or focused pytest command.
2. If the failure is e2e-only, inspect Docker logs and rerun the smallest failing scenario.
3. If the failure is workflow or packaging related, validate the built wheel or Docker image locally before changing application code.

## Documentation sync trigger

Update this runbook whenever release checks, incident response steps, or supported operational commands change.
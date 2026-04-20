# Operational Runbooks

This file is the human-facing operational guide for common VibeSensor incidents and release checks. Developer quick commands live in [.github/copilot-instructions.md](../.github/copilot-instructions.md).

Prebuilt Pi access defaults (hotspot address, HTTP fallback, SSH defaults, and remote-simulator examples) live in [infra/pi-image/pi-gen/README.md](../infra/pi-image/pi-gen/README.md).

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

Run-history retention is enforced during startup maintenance. By default the Pi
prunes `complete` and `error` runs older than `logging.run_retention_days: 7`.
Raise or lower that value in the server config when the device needs a longer
or shorter local-history window.

## Diagnose high dropped frames

1. Confirm the health endpoint responds and inspect connected clients.
2. Check whether the simulator or live devices reproduce the drop pattern consistently.
3. Reduce Wi-Fi contention and confirm the Pi hotspot channel and proximity are reasonable.
4. If the problem is local-only, inspect Docker logs:

```bash
docker compose logs --tail 100
```

5. If file logging is enabled, use the `X-Request-ID` response header from the
   failing HTTP call to find the matching structured JSON app-log entry; the
   same `request_id` also appears on request-scoped `settings_change` audit
   events.
6. If the issue is on a Pi, also review systemd or journal output for the service and hotspot helpers.

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

## Diagnose service or hotspot startup failures

1. Check the systemd units first:

```bash
sudo systemctl status vibesensor.service vibesensor-hotspot.service --no-pager
sudo systemctl status vibesensor-hotspot-self-heal.timer --no-pager
```

2. Inspect the recent service logs:

```bash
sudo journalctl -u vibesensor.service -u vibesensor-hotspot.service -n 200 --no-pager
```

Linux, Docker, and Raspberry Pi backends run through Granian and `uvloop`
during startup. If the service exits before `/api/health` responds, confirm the
active environment still imports both cleanly:

```bash
python -c "import granian, uvloop"
```

3. Validate the on-device config before restarting anything:

```bash
/path/to/venv/bin/vibesensor-config-preflight /etc/vibesensor/config.yaml
```

4. For hotspot bring-up or DHCP failures, inspect the files under `/var/log/wifi/`:
   - `hotspot.log` — full timestamped hotspot script output
   - `summary.txt` — last status/rc plus effective interface, SSID, and IP
   - `*_nm_dev.txt`, `*_nm_conn_active.txt`, `*_rfkill.txt` — captured NetworkManager/radio diagnostics
5. If the hotspot service failed after boot, restart only the AP path first:

```bash
sudo systemctl restart vibesensor-hotspot.service
```

6. If the backend service is unhealthy after a config change or package update, restart it separately:

```bash
sudo systemctl restart vibesensor.service
```

## Diagnose GPS timeout or missing speed

1. Confirm whether GPS is even enabled in the active config (`gps.gps_enabled`).
2. Check the daemon status:

```bash
sudo systemctl status gpsd --no-pager
```

3. If `gpsd-clients` is installed on the Pi image/manual install path, confirm
   the device is producing fixes:

```bash
cgps -s
```

4. If `/api/health` is good but speed stays empty, verify the configured speed
   source and whether the environment has enough sky view or signal quality for
   a lock.
5. For indoor benches or weak-signal environments, prefer a non-GPS speed path
   in config instead of repeatedly treating poor satellite reception as a server
   failure.

## Diagnose storage or history DB write problems

1. Start with `/api/health` and look for persistence-facing degradation reasons
   such as `persistence_write_error`, `persistence_samples_dropped`, or
   `last_analysis_failed`.
2. Check disk headroom before chasing application logic:

```bash
df -h /var/lib/vibesensor /var/log/vibesensor
```

3. Review recent backend service logs:

```bash
sudo journalctl -u vibesensor.service -n 200 --no-pager
```

4. If file logging is enabled, inspect the structured app log configured by
   `logging.app_log_path`.
5. Before any manual DB recovery, copy `/var/lib/vibesensor/history.db` off the
   device (or snapshot the card) so the original evidence is preserved.
6. If the device lost power and now reports repeated write failures, treat that
   as storage integrity or free-space triage first, then rerun the health checks
   before attempting new recordings.

## Update and rollback checks

1. Confirm current runtime and update status from the UI or update endpoints.
2. Before shipping a release, ensure the `release` job in the main release workflow builds the wheel, publishes the Wheel / ESP artifacts, and passes the smoke validation step.
3. Treat the `release` job itself as the complete release gate: it must build the wheel, publish the Wheel / ESP artifacts, and pass the smoke validation step before you treat the release as shipped.
4. If an update fails on-device, do not assume rollback succeeded silently. Confirm service health after the attempt and check updater issues for rollback wheel validation failures.
5. The updater now aborts before touching the live environment if it cannot write a fresh rollback snapshot or cannot verify free disk space for the rollback area. Treat either condition as an infrastructure problem to fix first, not a retry-until-it-works event.
6. If rollback metadata is missing, the updater will only trust the newest rollback wheel after structural archive validation; if checksum metadata exists, a mismatch should be treated as a broken rollback snapshot, not a transient install failure.
7. The Update panel now shows operational health from `/api/health`; use its degradation reasons, data-loss counts, and persistence status as the first operator-facing signal before digging through logs. Key degradation reasons include `persistence_write_error` (DB write failures), `persistence_samples_dropped` (samples lost during recording), and `last_analysis_failed` (most recent post-analysis run errored). The health response also exposes `samples_written`, `samples_dropped`, `last_completed_run_id`, and `last_completed_run_error` in its persistence section for detailed diagnostics.
8. If emergency patching was used to restore service, follow up with the repo fix, validation, and a successful updater rerun so the device returns to wheel-managed state.

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
On Linux/Docker/Pi, this stack should be running on Granian with the canonical
`uvloop` event loop by default; unsupported non-Linux local development is the
only place the default asyncio loop remains expected.

## CI failure triage

When a PR check fails:

1. Reproduce the failing job locally with the matching `run_ci_parallel.py` or focused pytest command.
2. If the failure is e2e-only, inspect Docker logs and rerun the smallest failing scenario.
3. If the failure is workflow or packaging related, validate the built wheel or Docker image locally before changing application code.

## Documentation sync trigger

Update this runbook whenever release checks, incident response steps, or supported operational commands change.

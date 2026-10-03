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

Use `subsystems` for machine-readable triage. Each subsystem reports
`status: ready | degraded | unhealthy` and stable `reason_codes`; keep using the
top-level `status` and `degradation_reasons` for compatibility with older tools.

Run-history retention is enforced during startup maintenance: `complete` and
`error` runs older than 7 days (`RUN_RETENTION_DAYS` in
`apps/server/vibesensor/app/composition.py`) are pruned together with
their raw/whole-run sidecars.

Mutating local HTTP calls (`POST`, `PUT`, `PATCH`, `DELETE`) are protected by a
same-origin guard. Browser requests with an `Origin` or `Referer` for a different
host than the request `Host` return `403`; same-origin UI requests and local
tools such as `curl` without browser origin headers continue to work. If an
operator reports a blocked settings/update/history action, compare the browser
URL, proxy host, and request `Host` header before changing server config.

## Read structured backend logs

The console (`docker compose logs`, `journalctl -u vibesensor.service`) shows one
line per event: `<UTC timestamp> [level] message [logger] key=value ...`. When
`logging.app_log_path` is set, the same events are written as one JSON object per
line with `timestamp`, `level`, `logger`, `message`, `event`, `request_id` (for
request-scoped events), `exception` (when present), and the event's extra fields.

Useful events:

- `http_request` / `http_request_failed` with `method`, `path`, `status_code`,
  `duration_ms`, and `request_id` (echoed in the `X-Request-ID` response header)
- `settings_change` audit entries with `before` / `after`
- `run_lifecycle` (`run_action` `started` / `stopped`) and
  `run_finalize_stage_result` (one per finalization stage)
- `post_analysis_started` / `post_analysis_completed`, and `post_analysis_step`
  (one per post-analysis step with `step`, `step_status`, `duration_ms`,
  `details`) or `post_analysis_failed` / `post_analysis_retryable_failure`

```bash
grep '"event": "post_analysis_step"' /path/to/app.log | tail -n 20
```

## Diagnose high dropped frames

1. Confirm the health endpoint responds and inspect connected clients.
2. Check whether the simulator or live devices reproduce the drop pattern consistently.
3. Reduce Wi-Fi contention and confirm the Pi hotspot channel and proximity are reasonable.
4. If the problem is local-only, inspect Docker logs:

```bash
docker compose logs --tail 100
```

5. Use `docker compose logs --tail 100` for the human-readable console stream.
   If file logging is enabled, use the `X-Request-ID` response header from the
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

   The timer runs the hotspot watchdog every 2 minutes. When `VibeSensor-AP` is
   not active and no other connection (such as the updater's Wi-Fi uplink) owns
   `wlan0`, it retries `nmcli connection up` with backoff and then restarts
   `vibesensor-hotspot.service` to re-provision the profile. Its log lines are
   in `journalctl -t vibesensor-hotspot-selfheal`.

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

4. Review the live console output first with `journalctl` above. If file
   logging is enabled, inspect the matching structured JSON app log configured
   by `logging.app_log_path`, especially `post_analysis_step` and
   `post_analysis_failed` events around the same time.
5. Before any manual DB recovery, copy `/var/lib/vibesensor/history.db` off the
   device (or snapshot the card) so the original evidence is preserved.
6. If the device lost power and now reports repeated write failures, treat that
   as storage integrity or free-space triage first, then rerun the health checks
   before attempting new recordings.

## Update and revert checks

1. Confirm current runtime and update status from the UI or update endpoints.
2. Before shipping a release, ensure the `release` job in the main release workflow builds the wheel, publishes the Wheel / ESP artifacts, and passes the smoke validation step.
3. Treat the `release` job itself as the complete release gate: it must build the wheel, publish the Wheel / ESP artifacts, and pass the smoke validation step before you treat the release as shipped.
4. Updates never modify the running version. The release is installed into a new venv
   slot (`/opt/VibeSensor/apps/server/.venv/slots/<version>`) and smoke-tested in an
   isolated server on port 18082. Only then does `.venv/current` switch to it and the
   service restart. If install or smoke test fails, the update fails and the device
   keeps running the old slot unchanged.
5. After the restart, the boot check (the new slot's `bin/vibesensor-server`
   launcher) reverts automatically to the previous slot when the new version exits
   twice before becoming healthy, or is not healthy (`/api/health` ready, no failed
   startup tasks) within 60 s. The next startup reports this as a failed update:
   "Version X did not start healthy; reverted to Y". While a boot check is pending,
   new updates are refused with "The previous update is still being verified".
6. Inspect the slot state on the device:

   ```bash
   ls -l /opt/VibeSensor/apps/server/.venv/            # current -> slots/<version>
   ls /opt/VibeSensor/apps/server/.venv/slots/         # active + previous
   cat /opt/VibeSensor/apps/server/.venv/boot-pending.json 2>/dev/null
   sudo journalctl -u vibesensor.service | grep boot-check
   ```

   To revert by hand, run as the service user: `ln -sfn slots/<previous>
   /opt/VibeSensor/apps/server/.venv/current.tmp && mv -T
   /opt/VibeSensor/apps/server/.venv/current.tmp
   /opt/VibeSensor/apps/server/.venv/current`. Then run `sudo systemctl restart
   vibesensor.service`.
   Devices flashed before A/B slots have a plain `.venv`. Their first slot update moves
   it into `slots/<running version>` once. Updates need about 600 MiB free on that
   filesystem.
7. The Update panel now shows operational health from `/api/health`; use its degradation reasons, data-loss counts, and persistence status as the first operator-facing signal before digging through logs. Key degradation reasons include `persistence_write_error` (DB write failures), `persistence_samples_dropped` (samples lost during recording), and `last_analysis_failed` (most recent post-analysis run errored). The health response also exposes `samples_written`, `samples_dropped`, `last_completed_run_id`, and `last_completed_run_error` in its persistence section for detailed diagnostics.
8. Manual Pi installs create `/etc/sudoers.d/vibesensor-update` for the service
   user. It must point at
   `/opt/VibeSensor/apps/server/scripts/vibesensor_update_sudo.sh` for the
   standard install layout; custom clone paths must use the exact installed
   script path.
9. If emergency patching was used to restore service, follow up with the repo fix, validation, and a successful updater rerun so the device returns to wheel-managed state.

## Local release readiness

Run these before treating a branch as release-ready:

```bash
make lint
make typecheck-backend
make ui-typecheck
make coverage
make ci
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

1. Reproduce the failing job locally with the matching `make` target or focused pytest command.
2. If the failure is e2e-only, read the server/app log tails attached to the failing test report and rerun the smallest failing scenario with `pytest -q -n 0 apps/server/tests_e2e/<file>::<test>`.
3. If the failure is workflow or packaging related, validate the built wheel or Docker image locally before changing application code.

## Documentation sync trigger

Update this runbook whenever release checks, incident response steps, or supported operational commands change.

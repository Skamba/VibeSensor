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

Data-loss warnings (`frames_dropped`, `buffer_overflow_drops`,
`queue_overflow_drops`, `server_queue_drops`, `parse_errors`) come from
`recent_data_loss`, which covers the last 60 s (`window_s`). `frames_dropped`
warns only when a sensor lost at least 1 % of its recent frames
(`frame_loss_clients`), so an occasional lost Wi-Fi datagram does not warn.
`data_loss` keeps the totals since start for diagnostics; they never reset and
no longer keep `status` at `warn`. The dashboard's frame-loss chip uses the
same per-sensor `frame_loss_recent` flag.

Some frame loss is expected and stays out of `frames_dropped` warnings and
capture readiness: the frames a sensor loses in the first 5 s of its stream
(it buffers while the server is down and old frames age out at the first ACKs)
and the frames lost while a Bluetooth OBD scan or pairing has the Pi's shared
radio (plus 3 s for frames in flight). They still count in
`data_loss.frames_dropped`; `recent_data_loss.expected_frames_dropped` and the
per-client `expected_frames_dropped` / `last_expected_loss_reason`
(`stream_start`, `bluetooth_scan`, `bluetooth_pairing`) show them. Scans and
pairing are refused with 409 while a recording runs.

Use `subsystems` for machine-readable triage. Each subsystem reports
`status: ready | degraded | unhealthy` and stable `reason_codes`; keep using the
top-level `status` and `degradation_reasons` for compatibility with older tools.

Run-history retention is enforced during startup maintenance: `complete` and
`error` runs older than 7 days (`RUN_RETENTION_DAYS` in
`apps/server/vibesensor/app/composition.py`) are pruned together with
their raw-capture sidecars.

Mutating local HTTP calls (`POST`, `PUT`, `PATCH`, `DELETE`) are protected by a
same-origin guard. Browser requests with an `Origin` or `Referer` for a different
host than the request `Host` return `403`; same-origin UI requests and local
tools such as `curl` without browser origin headers continue to work. If an
operator reports a blocked settings/update/history action, compare the browser
URL, proxy host, and request `Host` header before changing server config.

## Read structured backend logs

The console (`docker compose logs`, `journalctl -u vibesensor.service`) shows one
line per event: `<UTC timestamp> [level] message [logger] key=value ...`. When
`logging.app_log_path` is set (on the Pi: `/var/lib/vibesensor/app.log`), the same events are written as one JSON object per
line with `timestamp`, `level`, `logger`, `message`, `event`, `request_id` (for
request-scoped events), `exception` (when present), and the event's extra fields.

Useful events:

- `http_request` / `http_request_failed` with `method`, `path`, `status_code`,
  `duration_ms`, and `request_id` (echoed in the `X-Request-ID` response header).
  Only mutations, `4xx`/`5xx` responses and requests slower than 1 s are logged
  at info; routine reads (UI polling, phone connectivity probes) log at debug.
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

1. Confirm the health endpoint responds and inspect connected clients. Compare
   `recent_data_loss.frames_dropped` (last minute) with `data_loss.frames_dropped`
   (since start) to tell ongoing loss from a past burst. Subtract
   `ingest.clients[].expected_frames_dropped` for loss with a known cause
   (`last_expected_loss_reason`).
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

## Diagnose a wrong Pi clock or run times

The Pi has no RTC. Without internet, systemd-timesyncd restores the clock from
the last saved time, so it can be days or months behind. Every time the UI
connects it posts the browser clock and IANA time zone to
`POST /api/system/browser-clock`. The server steps the system clock to the
browser clock once per process, and only when all of these hold:

- the kernel reports the clock as unsynchronised (no NTP sync; `adjtimex`
  returns `TIME_ERROR`);
- it is more than 10 s off;
- no run is recording.

The step needs `CAP_SYS_TIME`, which `vibesensor.service` grants. Look for
`Stepped the unsynchronised system clock` (warning) or `no CAP_SYS_TIME` (info)
in the journal. The response's `action` says what happened. Sensor timing runs
on the monotonic clock, so a step does not disturb sync. The step is not
persisted, so after a reboot without internet the next UI connection corrects
the clock again.

Reports show run times in the stored browser time zone, at the run's own date
(DST-correct). They fall back to the offset recorded with the run until a
browser has reported a zone. The History list formats times in the viewing
browser's zone.

```bash
timedatectl show --property=NTPSynchronized --value
journalctl -u vibesensor --no-pager | grep -E 'system clock|CAP_SYS_TIME'
```

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
   `GET /api/update/status` `runtime.commit` is the commit the release was built
   from (stamped into `vibesensor/_version.py` by `build-wheel` and the pi-gen
   artifact build; a git checkout reports its HEAD). The `static_build_*` fields
   come from the UI build record (`static/.vibesensor-ui-build.json`) shipped in
   the wheel, and `assets_verified` means the packaged assets still hash to that
   record. The release smoke step fails if the wheel lacks the record.
2. Before shipping a release, ensure the `release` job in the main release workflow builds the wheel and the Pi dependency wheelhouse, publishes the Wheel / ESP artifacts, and passes the smoke validation step.
3. Treat the `release` job itself as the complete release gate: it must build the wheel, publish the wheel, wheelhouse, and ESP artifacts, and pass the smoke validation step before you treat the release as shipped.
   The wheelhouse (`vibesensor-wheelhouse-<version>-cp313-linux_armv7l.tar`) holds
   every runtime dependency as armv7l/CPython 3.13 wheels from PyPI and piwheels. If
   `build-wheelhouse` fails because a dependency has no binary Pi wheel yet, pin that
   dependency to the last version piwheels has built, or wait for piwheels to build it.
4. Updates never modify the running version. The release wheel and wheelhouse are
   downloaded and SHA-256-verified against the GitHub asset digests. Then the
   release is installed with its dependencies, offline (`pip install --no-index
   --find-links <wheelhouse>`), into a fresh venv slot
   (`/opt/VibeSensor/apps/server/.venv/slots/<version>`). That slot is smoke-tested
   in an isolated server on port 18082. Only then does `.venv/current` switch to it
   and the service restart. If install or smoke test fails, the update fails and the
   device keeps running the old slot unchanged. Dependency changes therefore no
   longer need a reflash.
5. After the restart, the boot check (the new slot's `bin/vibesensor-server`
   launcher) reverts automatically to the previous slot when the new version exits
   twice before becoming healthy, or does not work within 60 s. "Works" means
   `/api/health` answers with `startup_state: ready`, no `startup_error`, no failed
   startup tasks, no database corruption, and `processing_state: ok`. The overall
   `status` does not count: `warn` or `degraded` from sensors or the device
   (dropped frames, no GPS receiver, a sensor still to be flashed, an outdated root
   side) is not reverted, because the previous version would not fix it. The boot
   check is the one from the release that installed the update, so updates started
   from releases before this rule still revert on `warn`. The next startup reports
   this as a failed update:
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
   filesystem (new slot plus the staged wheelhouse under `.venv/.staging-*`).
7. The Update panel now shows operational health from `/api/health`; use its degradation reasons, data-loss counts, and persistence status as the first operator-facing signal before digging through logs. Key degradation reasons include `persistence_write_error` (DB write failures), `persistence_samples_dropped` (samples lost during recording), and `last_analysis_failed` (most recent post-analysis run errored). A `root_side` subsystem marked `root_side_outdated` means the installed root-side helpers and units are not the ones this release ships; the panel names the fix (see [Installing a release's root side](#installing-a-releases-root-side)). It does not block updates. The health response also exposes `samples_written`, `samples_dropped`, `last_completed_run_id`, and `last_completed_run_error` in its persistence section for detailed diagnostics.
8. Root commands (Wi-Fi uplink and hotspot `nmcli` calls, the privilege probe,
   the post-update restart, Bluetooth OBD scan/pair) go through the privileged
   helper, never sudo. `vibesensor.service` runs with `NoNewPrivileges=true`,
   which makes sudo refuse to run. The server connects to
   `/run/vibesensor-privileged.sock` (`vibesensor-privileged.socket`, owned by
   the service user, mode 0600). For each connection systemd starts a
   `vibesensor-privileged@.service` instance as root. That instance runs
   `/usr/bin/python3 -I /usr/local/lib/vibesensor/vibesensor_privileged_helper.py`,
   which passes the request only to the allowlist wrapper it names:
   `vibesensor_update_allowlist.sh` or `vibesensor_obd_admin.py`. Check it with
   `systemctl status vibesensor-privileged.socket` and
   `journalctl -t vibesensor-privileged`. "Privileged helper socket ... is
   unavailable" in the update log or OBD status means the socket units are
   missing; see the migration below. See
   [Root runs only root-owned code](#root-runs-only-root-owned-code) for what
   root executes and how releases change it.
9. If emergency patching was used to restore service, follow up with the repo fix, validation, and a successful updater rerun so the device returns to wheel-managed state.

## Root runs only root-owned code

The service user (`pi`) owns the A/B venv, and on manual installs usually the
git clone too. Anything root executes from there would let a compromised
server become root. So root never does:

- Every root-side helper lives in `apps/server/root-helpers/`:
  `vibesensor_privileged_helper.py`, `vibesensor_update_allowlist.sh`,
  `vibesensor_obd_admin.py`, `hotspot_nmcli.sh`, and `vibesensor_hotspot.py`.
  They use only the standard library (plus Debian's `python3-yaml` for the
  hotspot config) and never import the `vibesensor` package.
- `apps/server/scripts/install_systemd_units.sh` copies them into
  `/usr/local/lib/vibesensor` (`root:root`, mode 0755). `install_pi.sh` and
  the image build run it.
- The root units run those copies only: `vibesensor-privileged@.service`
  (privileged helper), `vibesensor-hotspot.service` (`hotspot_nmcli.sh`), and
  `vibesensor-hotspot-self-heal.service` (`vibesensor_hotspot.py watchdog`).
  Python always runs as the system `/usr/bin/python3 -I`, so neither the venv
  interpreter nor `PYTHONPATH`, the working directory, or user site-packages
  can inject code.
- The server itself stays on the venv as the service user and only talks to
  root through the socket.

Check a device with `ls -l /usr/local/lib/vibesensor` (all `root root`, no
group or world write) and `systemctl cat vibesensor-privileged@.service
vibesensor-hotspot.service vibesensor-hotspot-self-heal.service | grep Exec`.
Image validation and `tests/hygiene/test_pi_image_static_guardrails.py` fail
if a root unit runs anything the service user can write.

### Installing a release's root side

The root side is `apps/server/root-helpers/`, `scripts/`, and `systemd/`.
In-app updates (Wi-Fi and USB) run as the service user and replace only the
venv. They never touch `/usr/local/lib/vibesensor` or the unit files. A release
that changes the root side takes effect only when an operator installs it from
that release's tree (works offline).

**How you notice.** `install_systemd_units.sh` writes a manifest of the tree it
installed from to `/usr/local/lib/vibesensor/root-side.sha256`: one
`sha256sum` line per regular file in the three directories, sorted. Every app
release carries the digest of its own manifest (`ROOT_SIDE_DIGEST` in
`vibesensor/common/root_side.py`). When the two differ, or the stamp is
missing, `/api/health` reports `root_side.state: "outdated"` and marks the
`root_side` subsystem degraded (`root_side_outdated`). The Update tab shows the
fix with the release tag. The overall `status` stays out of it, so it neither
blocks in-app updates nor makes the post-update boot check revert them. Until
the root side matches, hotspot repair (`vibesensor-hotspot.service`, the
self-heal timer) and Bluetooth OBD scan/pair can fail. A device installed before the stamp existed always shows
as outdated until its root side is reinstalled once. Compare by hand with
`sha256sum < /usr/local/lib/vibesensor/root-side.sha256` against
`expected_digest` in `/api/health`.

To install it:

- **Git install (`install_pi.sh`):** in the clone, `git fetch --tags && git
  checkout server-v<version>` (the version the Update tab shows), then
  `sudo ./apps/server/scripts/install_systemd_units.sh`. Before you run `sudo`
  from a clone the service user can write, check it with `git status` and
  `git log` (or use a fresh clone): that run is the point where root trusts
  the tree.
- **Prebuilt image:** reflash, or from a checkout of `server-v<version>` on a
  computer joined to the hotspot run
  `apps/server/scripts/push_root_side.sh pi@10.4.0.1`. It asks for the `pi`
  password and the `sudo` password.

`push_root_side.sh` computes the manifest digest of your checkout before it
copies anything. The files reach the Pi through `/tmp/vibesensor-root-side`,
which `pi` (the service user) can write. So root first copies them into a
private `mktemp -d` directory and checks that copy against the digest from your
computer. Only then does it move them into the root-owned
`/opt/VibeSensor/apps/server` and run `install_systemd_units.sh` from there. A
file changed on the way stops the install before root runs anything from it.
The script refuses to install if `/opt/VibeSensor/apps/server` or a parent can
be written by anyone but root. Neither path protects a device whose `pi`
account is already compromised, because that account sees your `sudo`
password. Reflash such a device.

This step is deliberately manual. Letting the updater install root-side files
would mean root trusting a download that the service user fetched and staged,
which reopens the same hole. Signing releases could close it, but that adds key
management for a handful of rarely changed files. Until an operator installs
the new root side, the old helpers keep running with the new server. Keep the
socket request format and the allowlist arguments backward-compatible across
releases. Any change under the three directories changes `ROOT_SIDE_DIGEST`
(`tests/hygiene/test_root_side.py` fails until you update it), so the release
notes must tell operators to reinstall the root side.

## One-time migration to the privileged helper

Devices installed before the privileged helper granted the service user sudo on
`vibesensor_update_sudo.sh`. Their hardened `vibesensor.service`
(`NoNewPrivileges=true`, two-capability bounding set) makes sudo refuse. So on
those devices the in-app update (Wi-Fi and USB), the hotspot recovery, and
Bluetooth OBD scan/pair all fail, and the updater cannot install the fix itself.
Migrate each device once by hand. You need SSH and the `pi` password.

- **Manual installs (git clone):** `git pull`, then
  `sudo ./apps/server/scripts/install_pi.sh` (needs internet). It installs the
  socket units, removes `/etc/sudoers.d/vibesensor-update`, and restarts the
  server.
- **Prebuilt image, reflash:** back up `/var/lib/vibesensor/` and
  `/etc/vibesensor/config.yaml`, flash an image built from a release that has
  the privileged helper, then restore both.
- **Prebuilt image, in place:** let the old updater run once without the
  hardening, then install the new root side.
  1. Add a runtime-only drop-in (gone after a reboot) so the old sudo-based
     updater can work:

     ```bash
     ssh -t pi@10.4.0.1
     sudo mkdir -p /run/systemd/system/vibesensor.service.d
     printf '[Service]\nNoNewPrivileges=no\nCapabilityBoundingSet=~\n' |
       sudo tee /run/systemd/system/vibesensor.service.d/migrate.conf
     sudo systemctl daemon-reload && sudo systemctl restart vibesensor.service
     ```

  2. In the UI, update to a release that has the privileged helper (Wi-Fi or
     USB). Wait until the server is back on the new version.
  3. From a checkout of that release (`server-v<version>`) on a computer joined
     to the hotspot:

     ```bash
     apps/server/scripts/push_root_side.sh pi@10.4.0.1
     ```

  `push_root_side.sh` checks the files on the Pi against your checkout before
  root uses them. It also removes the step-1 drop-in. See
  [Installing a release's root side](#installing-a-releases-root-side).
  `install_systemd_units.sh` works offline. It installs the root-side helpers
  into `/usr/local/lib/vibesensor`, re-renders every unit, installs and starts
  `vibesensor-privileged.socket`, removes the stale sudoers entry and the old
  helper copies under `apps/server/scripts/`, writes the root-side stamp, and
  restarts the server. Releases from before `push_root_side.sh` do not ship
  it. Run it from a newer checkout only if that release's root side is the
  same, or reflash.

Devices that already have the privileged helper but still run root code from
the install tree or the venv (releases before root-owned helpers) need only
step 3. Do not skip it. An in-app update leaves those devices on their old
units, and the new venv no longer ships the modules those units ran. So
`vibesensor-hotspot.service` (hotspot re-provisioning), the self-heal timer and
OBD scan/pair fail until the device is migrated. The saved `VibeSensor-AP`
connection still comes up through NetworkManager, and updates and the Wi-Fi
uplink keep working, so the device stays reachable for the migration.

Afterwards, `systemctl is-active vibesensor-privileged.socket` prints `active`,
`/etc/sudoers.d/vibesensor-update` is gone, `/usr/local/lib/vibesensor` holds
the root-owned helpers, `systemctl start vibesensor-hotspot-self-heal.service`
succeeds, `/api/health` reports `root_side.state: "current"`, and the Update
panel can start an update.

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

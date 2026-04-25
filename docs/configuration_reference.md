# Configuration Reference

Scope: operator-facing reference for the YAML runtime configuration accepted by
`vibesensor.app.config_loader.load_config()`.

The source of truth for defaults lives in
`apps/server/vibesensor/app/config_defaults.py`. Typed validation and clamping
live in `apps/server/vibesensor/app/config_schema.py`. This document exists so
operators do not need to read Python source just to discover the supported keys.

## How to inspect and validate config

Dump the documented defaults:

```bash
vibesensor-config-preflight --dump-defaults
```

Validate a resolved YAML file:

```bash
vibesensor-config-preflight /etc/vibesensor/config.yaml
```

Load order is:

1. built-in defaults
2. selected YAML override file
3. typed validation/clamping from the config schema

For local development examples, see `apps/server/config.dev.yaml`,
`apps/server/config.docker.yaml`, and `apps/server/config.pi.yaml`.

## `ap`

| Key | Default | Notes |
|-----|---------|-------|
| `ap.ssid` | `VibeSensor` | Hotspot SSID. Change this before real deployments. |
| `ap.psk` | `""` | Empty string means an open AP. Set a PSK for non-prototype deployments. |
| `ap.ip` | `10.4.0.1/24` | Hotspot subnet/address used by NetworkManager shared mode. |
| `ap.channel` | `7` | 2.4 GHz Wi-Fi channel. The typed config accepts channels `1`-`14`. |
| `ap.ifname` | `wlan0` | Preferred Wi-Fi interface name. The hotspot script falls back to a detected Wi-Fi device if this one is missing. |
| `ap.con_name` | `VibeSensor-AP` | NetworkManager connection profile name for the hotspot. |
| `ap.self_heal.enabled` | `true` | Enable the hotspot self-heal watchdog/timer. |
| `ap.self_heal.diagnostics_lookback_minutes` | `5` | Positive integer window for hotspot diagnostics lookback. |
| `ap.self_heal.min_restart_interval_seconds` | `120` | Minimum seconds between self-heal restarts. Non-negative integer. |
| `ap.self_heal.state_file` | `data/hotspot-self-heal-state.json` | Writable state file used by the self-heal logic. Pi deployments override this into `/var/lib/vibesensor/`. |

## `server`

| Key | Default | Notes |
|-----|---------|-------|
| `server.host` | `0.0.0.0` | Bind host for the FastAPI server. |
| `server.port` | `80` | TCP port for HTTP/UI traffic. Must stay within `1`-`65535`. Dev configs typically override this to `8000`. |

## `udp`

| Key | Default | Notes |
|-----|---------|-------|
| `udp.data_host` | `0.0.0.0` | Bind host for sensor data packets. |
| `udp.data_port` | `9000` | UDP port for sensor data. Must stay within `1`-`65535`. |
| `udp.control_host` | `0.0.0.0` | Bind host for control/ACK traffic. |
| `udp.control_port` | `9001` | UDP port for control traffic. Must stay within `1`-`65535`. |
| `udp.data_queue_maxsize` | `1024` | Max async UDP queue depth before packets are dropped and counted. Must be `>= 1`. |

## `processing`

| Key | Default | Notes |
|-----|---------|-------|
| `processing.sample_rate_hz` | `800` | Expected live sample rate for metrics/FFT processing. Values below `1` clamp to `1`. |
| `processing.waveform_seconds` | `8` | Ring-buffer window length per client. Values below `1` clamp to `1`, and very large values are clamped so `sample_rate_hz * waveform_seconds` stays within the per-client buffer limit. |
| `processing.client_live_ttl_seconds` | `10` | How long clients remain `connected: true` after their last packet. |
| `processing.client_ttl_seconds` | `120` | Longer metadata retention window after clients go stale. Clamped up to at least `client_live_ttl_seconds`. |
| `processing.accel_scale_g_per_lsb` | `null` | Optional raw accelerometer scale factor. Leave unset when the sender already emits values in g. |

## `logging`

| Key | Default | Notes |
|-----|---------|-------|
| `logging.history_db_path` | `data/history.db` | Persisted history/settings database path. Pi deployments override this to `/var/lib/vibesensor/history.db`. |
| `logging.metrics_log_hz` | `4` | Live metrics logging cadence. Invalid values clamp up to at least `1`. |
| `logging.no_data_timeout_s` | `15.0` | Auto-stop timeout when recording stops seeing new data. Invalid values clamp to `15.0`. |
| `logging.persist_history_db` | `true` | Enable/disable writing run history to the DB. |
| `logging.run_retention_days` | `7` | Startup maintenance retention window for terminal runs (`complete` / `error`). Full run deletion still removes samples plus raw/whole-run sidecars. Invalid values clamp up to at least `1`. |
| `logging.raw_capture_retention_days` | `7` | Optional shorter retention window for raw waveform sidecars while keeping compact run summaries. Only applied when lower than `logging.run_retention_days`. Invalid values clamp up to at least `1`. |
| `logging.shutdown_analysis_timeout_s` | `30` | How long shutdown waits for post-analysis cleanup before giving up. Invalid values clamp to `30.0`. |
| `logging.app_log_path` | `data/app.log` | Structured JSON application-log output path. Set to `null` if file logging is not wanted. |

## `gps`

| Key | Default | Notes |
|-----|---------|-------|
| `gps.gps_enabled` | `true` | Enable gpsd-backed GPS reads. Disable this on dev benches or deployments without GPS hardware. |
| `gps.gpsd_host` | `127.0.0.1` | gpsd host. |
| `gps.gpsd_port` | `2947` | gpsd port. Must stay within `1`-`65535`. |

## `update`

| Key | Default | Notes |
|-----|---------|-------|
| `update.rollback_dir` | `/var/lib/vibesensor/rollback` | Rollback snapshot directory used by the updater. Keep this on writable persistent storage. |

## Common operator overrides

```yaml
# secure the default hotspot
ap:
  ssid: VibeSensor-Workshop
  psk: change-me-first

# dev bench without GPS and with the backend on :8000
server:
  port: 8000
gps:
  gps_enabled: false

# retain run history longer on a device with more storage
logging:
  run_retention_days: 30
  raw_capture_retention_days: 7
```

Use `apps/server/config.pi.yaml` as the starting point for Pi installs and the
other preset configs as examples for dev/docker environments.

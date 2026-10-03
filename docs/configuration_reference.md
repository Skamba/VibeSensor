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
3. typed validation from the config schema

Only settings that differ between deployments (dev, Docker, Pi, isolated test
runtimes) or that the operator owns (hotspot SSID/PSK) are configurable. Fixed
tuning values live as Python constants next to the code that uses them (for
example the live sample rate in `vibesensor/dsp/constants.py`, hotspot
address/channel/interface in `vibesensor/hotspot/constants.py`, and
run retention in `vibesensor/app/composition.py`).

Keys that are not listed below are ignored with an
`Ignoring unsupported config key <key>` warning, so device configs written by
older releases (which accepted keys such as `processing.*`, `ap.channel`,
`update.rollback_dir`, or `logging.run_retention_days`) keep loading unchanged.

For local development examples, see `apps/server/config.dev.yaml`,
`apps/server/config.docker.yaml`, and `apps/server/config.pi.yaml`.

## `ap`

| Key | Default | Notes |
|-----|---------|-------|
| `ap.ssid` | `VibeSensor` | Hotspot SSID. Change this before real deployments. |
| `ap.psk` | `""` | Empty string means an open AP. Set a PSK for non-prototype deployments. |

The hotspot address (`10.4.0.1/24`), channel (`7`), interface (`wlan0`, with a
detected-device fallback), and NetworkManager profile name (`VibeSensor-AP`)
are fixed in `vibesensor/hotspot/constants.py`. The hotspot watchdog
(`vibesensor-hotspot-self-heal.timer`) has no settings; older `ap.self_heal.*`
keys are ignored with a warning.

## `server`

| Key | Default | Notes |
|-----|---------|-------|
| `server.host` | `0.0.0.0` | Bind host for the FastAPI server. |
| `server.port` | `80` | TCP port for HTTP/UI traffic. Must stay within `1`-`65535`. Dev configs typically override this to `8000`. |

### Local mutation safety

There is no YAML switch for the local HTTP safety boundary. The server always
keeps read-only dashboard/API requests open, and it rejects mutating methods
(`POST`, `PUT`, `PATCH`, `DELETE`) when a browser sends an `Origin` or `Referer`
header for a different host than the request `Host`. Same-origin UI requests and
non-browser local clients without those headers remain allowed. Treat this as a
CSRF/trusted-origin guard, not login/authentication; secure deployments should
still set `ap.psk` and restrict who can join the local appliance network.

## `udp`

| Key | Default | Notes |
|-----|---------|-------|
| `udp.data_host` | `0.0.0.0` | Bind host for sensor data packets. |
| `udp.data_port` | `9000` | UDP port for sensor data. Must stay within `1`-`65535`. |
| `udp.control_host` | `0.0.0.0` | Bind host for control/ACK traffic. |
| `udp.control_port` | `9001` | UDP port for control traffic. Must stay within `1`-`65535`. |

## `logging`

| Key | Default | Notes |
|-----|---------|-------|
| `logging.history_db_path` | `data/history.db` | Persisted history/settings database path. Pi deployments override this to `/var/lib/vibesensor/history.db`. |
| `logging.app_log_path` | `data/app.log` | Structured JSON application-log output path. Set to `null` if file logging is not wanted. |

Terminal runs older than 7 days are pruned at startup (see
`docs/history_db_schema.md`).

## `gps`

| Key | Default | Notes |
|-----|---------|-------|
| `gps.gps_enabled` | `true` | Enable gpsd-backed GPS reads (gpsd on `127.0.0.1:2947`). Disable this on dev benches or deployments without GPS hardware. |

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
```

Use `apps/server/config.pi.yaml` as the starting point for Pi installs and the
other preset configs as examples for dev/docker environments.

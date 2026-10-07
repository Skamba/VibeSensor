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
the run-history free-space floor in `vibesensor/app/composition.py`).

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
| `ap.psk` | `""` | Empty string means an open AP. Set a PSK for non-prototype deployments. After changing `ap.ssid` or `ap.psk`, restart the Pi and re-flash every sensor from *Settings → Advanced → ESP Flash*: the flasher writes the current SSID/PSK into the sensor's NVS, while sensors flashed elsewhere only know the open `VibeSensor` network. Print a new hotspot card with `tools/hardware/make_qr_card.py` ([hardware/README.md](../hardware/README.md#hotspot-card)). |

The hotspot address (`10.4.0.1/24`), channel (`7`), interface (`wlan0`, with a
detected-device fallback), and NetworkManager profile name (`VibeSensor-AP`)
are fixed in `apps/server/root-helpers/vibesensor_hotspot.py`, the root-side
hotspot helper (`vibesensor/hotspot/constants.py` mirrors the values the server
needs).

The hotspot behaves as a captive portal with no setting: `hotspot_nmcli.sh`
writes `/etc/NetworkManager/dnsmasq-shared.d/vibesensor-captive-portal.conf`,
so the AP-only shared-mode dnsmasq resolves the OS connectivity-probe hosts
(listed in `root-helpers/vibesensor_hotspot.py` and
`vibesensor/hotspot/captive_portal.py`) to `10.4.0.1`, and the server
redirects any request for those hosts to `http://10.4.0.1/`. Phones then offer
to "sign in" and open the UI. Other names and the Pi's own resolver are
unchanged, so uplink updates are unaffected. The hotspot watchdog
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
| `logging.app_log_path` | `app.log` | Structured JSON application-log output path. A relative path resolves against the data directory (the folder of `logging.history_db_path`), so the Pi writes `/var/lib/vibesensor/app.log`, never into the read-only `/etc/vibesensor`. Set to `null` if file logging is not wanted. |

Runs are kept however old; only when the data disk has less than 1 GiB free
does startup delete the oldest finished runs (see `docs/history_db_schema.md`).

## `gps`

| Key | Default | Notes |
|-----|---------|-------|
| `gps.gps_enabled` | `true` | Enable gpsd-backed GPS reads (gpsd on `127.0.0.1`). Disable this on dev benches or deployments without GPS hardware. |
| `gps.gpsd_port` | `2947` | gpsd's TCP port. Only isolated test runtimes change it, to read the simulator's GPS feed (`vibesensor-sim --gps-port`). |

A receiver counts as present only when gpsd lists it (its `DEVICES`/`DEVICE`
reports, or a `TPV` naming a device), never from gpsd's own version banner, so
a running gpsd without a receiver shows "no receiver" instead of flickering.
While gpsd lists no receiver the server keeps its session and asks `?DEVICES;`
every few seconds, so a hot-plugged receiver shows up within about 3 s. Debian's
`60-gpsd.rules` leaves the PL2303 and CP210x USB-serial chips commented out;
`apps/server/systemd/61-vibesensor-gps.rules` (installed into
`/etc/udev/rules.d` by `install_systemd_units.sh`) enables them. The ATOM
Lite's FTDI chip stays excluded so gpsd never grabs a sensor being flashed; a
CP210x-based ESP32 board plugged into the Pi would be grabbed, so flash those
from another machine.

## `recording`

| Key | Default | Notes |
|-----|---------|-------|
| `recording.max_duration_s` | `1800` | A recording auto-stops (reason `max_duration`) after this many seconds, which keeps post-analysis within the Pi's memory budget. Only isolated test runtimes shorten it, to exercise the auto-stop. |

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

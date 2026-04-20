# VibeSensor

Portable, offline car vibration diagnostics using a Raspberry Pi and wireless accelerometer nodes.

## What Is VibeSensor?

VibeSensor is an end-to-end system that detects and localizes vehicle vibration issues — wheel imbalance, driveshaft rumble, engine harmonics — using low-cost hardware you can mount anywhere on a car. A Raspberry Pi runs as a standalone Wi-Fi access point, receives 800 Hz accelerometer streams from multiple ESP32 sensor nodes over UDP, performs real-time FFT analysis with automotive order tracking, and serves a mobile-friendly dashboard accessible from any phone or tablet. After a drive, it generates a professional PDF diagnostic report with findings, heatmaps, and evidence charts.

No internet connection required. No cloud. Everything runs locally on the Pi.

## Key Features

**Sensing & Analysis**
- Multi-sensor 3-axis accelerometer monitoring at 800 Hz (ADXL345)
- Real-time FFT spectrum with peak detection and noise floor estimation
- Automotive order tracking — wheel, driveshaft, and engine frequency bands
- Speed-adaptive analysis using GPS or manual speed input
- Configurable car profiles (tire specs, gear ratios, drive ratios)

**Dashboard**
- Live spectrum chart, car heatmap, and vibration event log
- Multi-sensor overview with identify-blink for physical location
- Recording controls with automatic silence detection
- Run history with per-run insights and PDF export
- Car settings wizard with vehicle library
- English and Dutch language support

**Deployment**
- Offline Wi-Fi access point with self-healing hotspot recovery
- Two deployment paths: manual install or prebuilt SD card image
- Docker Compose for desktop development and testing
- systemd services for automatic startup

**Developer Experience**
- Hardware simulator for full-stack testing without physical sensors
- Extensive pytest suite with CI integration
- Playwright visual regression tests across 4 viewports
- Ruff backend linting plus UI linting and TypeScript type checking enforced in CI
- Custom binary UDP protocol with sequence-based loss detection

## Units

See [docs/metrics.md](docs/metrics.md) for the unit rules and
vibration-metric definitions used throughout the repo.

## System Architecture

```
  ┌──────────────┐      UDP 9000 (data)       ┌──────────────────┐
  │  ESP32 + ────│──────────────────────────►  │  Raspberry Pi    │
  │  ADXL345     │      UDP 9001 (control)     │                  │
  │  sensor node │  ◄──────────────────────────│  FastAPI server  │
  └──────────────┘                             │  + FFT engine    │
                                               │  + report gen    │
                                               └────────┬─────────┘
                                                        │
        ┌───────────┐    HTTP (default 80; dev 8000) + WebSocket  ────────┘
        │  Phone /  │◄──────────────────────────────────
        │  Tablet   │   (live spectrum, controls, PDF)
        └───────────┘
```

Sensors connect to the Pi's Wi-Fi AP, stream accelerometer data via UDP, and the Pi pushes processed spectra and diagnostics to the browser over WebSocket. The phone just needs a browser — no app install.

## Repository Layout

```
apps/
  server/      Python backend (FastAPI + signal processing + reports)
  ui/          TypeScript frontend (Vite + uPlot)
firmware/
  esp/         ESP32 firmware (PlatformIO, C++)
infra/
  pi-image/    Raspberry Pi image build pipeline
docs/          Protocol spec, run schema, design language
hardware/      Bill of materials and wiring reference
tools/         Utilities (config checks, tests, support scripts)
artifacts/     Build/runtime artifacts (non-source)
```

Each component has its own README with setup instructions and details.

## Docs Index

See [docs/README.md](docs/README.md) for the complete documentation index.
For HTTP/WebSocket developer references, start with
[apps/server/README.md#http-and-websocket-surface](apps/server/README.md#http-and-websocket-surface)
and
[apps/ui/README.md#websocket-contract-boundary](apps/ui/README.md#websocket-contract-boundary),
then use the docs index for the broader map.
For supported Python and Node policy by environment, use
[docs/runtime_support_matrix.md](docs/runtime_support_matrix.md).

## Prerequisites

- The Python and Node versions from
  [docs/runtime_support_matrix.md](docs/runtime_support_matrix.md) for the
  workflow path you're using. Native dev and local CI reproduction follow
  [`.python-version`](.python-version) and [`.nvmrc`](.nvmrc).
- Docker plus Docker Compose for the Docker quick-start and Docker dev mode
- PlatformIO `6.x` only when you are working on firmware

Run `make doctor` after cloning to validate the pinned toolchain and see which
workflow paths are available on your machine. Run bare `make` to list the
supported repo commands.

## Quick Start

### Docker (quick product check)

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
docker compose up --build
```

In another terminal, start the simulator:

```bash
pip install -e "./apps/server[dev]"
vibesensor-sim --count 5 --server-host 127.0.0.1
```

Open http://localhost:8000.

If you want source-mounted hot-reload instead of a production-style container
build, use the Docker dev mode below.

### Docker dev mode (source-mounted hot reload)

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
make dev
```

Open http://127.0.0.1:5173 for the Vite dev server with HMR. The backend keeps
running on http://127.0.0.1:8000 with `vibesensor-server --reload`, so Granian
reloads Python changes without rebuilding the image.

`make dev` wraps `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`.
The UI container now reuses the `node_modules` volume unless `apps/ui/package-lock.json`
changes, it follows the supported Node line from [`.nvmrc`](.nvmrc), and it fails
fast if the generated frontend contracts are stale.

### Native Python + Vite (recommended for backend or UI iteration)

Use the native-dev Python from
[docs/runtime_support_matrix.md](docs/runtime_support_matrix.md) before creating
the virtualenv:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./apps/server[dev]"
npm --prefix apps/ui ci
vibesensor-server --reload --config apps/server/config.dev.yaml
```

The backend uses an editable install from `apps/server/pyproject.toml` so
commands like `vibesensor-server` and `vibesensor-sim` stay tied to your working
tree. A local virtualenv created from the matrix-supported native-dev Python is
the recommended path before you run the install above, and `make setup` will
create or refresh that `.venv` for you automatically.
On Linux, Docker, and Raspberry Pi runtimes, `vibesensor-server` runs the
backend through Granian with the canonical `uvloop` event loop. Unsupported
non-Linux local development falls back to Granian on the default asyncio loop.

In another terminal:

```bash
npm --prefix apps/ui run dev
vibesensor-sim --count 5 --server-host 127.0.0.1 --no-auto-server
```

Open http://localhost:5173 for HMR-backed development. The Vite dev server now
proxies `/api`, `/ws`, and `/static` to the backend on `:8000`. If you prefer a
static UI build instead of the dev server, run `python tools/build_ui_static.py`
and skip `npm --prefix apps/ui run dev`, then open http://localhost:8000.

Use [CONTRIBUTING.md](CONTRIBUTING.md) for the full validation, CI reproduction,
developer troubleshooting, and workflow guidance.

The simulator supports interactive commands — type `help` to see options like
`list`, `set <sensor> profile <name>`, `pulse`, `pause`, `resume`.

It also ships with scripted multi-phase runs via `--scenario`, including
acceleration/deceleration sweeps and temporary vibration windows. Example:

```bash
vibesensor-sim --count 5 --server-host 127.0.0.1 --scenario accel-front-left-surge
```

Run `vibesensor-sim --help` to see the full scripted scenario list.

## Deploying to Raspberry Pi

Both deployment modes target Raspberry Pi 3 A+ with Trixie Lite.

### Mode A: Manual install

Flash official Raspberry Pi OS Lite (Trixie), then on the Pi:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
sudo ./apps/server/scripts/install_pi.sh
sudo ./apps/server/scripts/hotspot_nmcli.sh
```

`install_pi.sh` validates the Pi's `python3` before creating the virtualenv and
fails fast when the interpreter is below the supported manual-install floor. See
[docs/runtime_support_matrix.md](docs/runtime_support_matrix.md) for the current
policy.

See [apps/server/README.md](apps/server/README.md) for configuration and uplink-update details.

### Mode B: Prebuilt image

Build on a Linux machine with Docker:

```bash
sudo apt-get update && sudo apt-get install -y docker.io qemu-user qemu-user-static rsync xz-utils
./infra/pi-image/pi-gen/build.sh
```

Flash the output image from `infra/pi-image/pi-gen/out/` and boot — no manual steps needed.

If you just need a ready-made artifact instead of building locally, GitHub
Releases also carries the latest automated weekly Pi image snapshot once the
weekly image workflow has run. The workflow rotates a single weekly Pi-image
prerelease, so Releases shows only the newest snapshot.

See [infra/pi-image/pi-gen/README.md](infra/pi-image/pi-gen/README.md) for details.

### Verification

Connect a phone to the `VibeSensor` Wi-Fi (the default config uses
an open AP with empty PSK) and open http://10.4.0.1. Sensor nodes should appear
within seconds.

> Default AP credentials are for prototype use only. Change SSID/PSK before
> real-world deployment.

For post-install config tuning, service management, and field troubleshooting,
use [apps/server/README.md](apps/server/README.md),
[docs/configuration_reference.md](docs/configuration_reference.md), and
[docs/operational-runbooks.md](docs/operational-runbooks.md).

## ESP Sensor Setup

```bash
cd firmware/esp
pio run -t upload
pio device monitor
```

Defaults match the Pi hotspot out of the box. See [firmware/esp/README.md](firmware/esp/README.md)
for network overrides and pin configuration.

## Protocol Summary

UDP datagrams between ESP32 nodes and the Pi:

| Type | ID | Purpose |
|------|----|---------|
| HELLO | 1 | Client identity, name, firmware version, control port |
| DATA | 2 | Accelerometer sample frames with sequence numbers |
| CMD | 3 | Server → client command (e.g., identify blink) |
| ACK | 4 | Command acknowledgment |
| DATA_ACK | 5 | Data receipt acknowledgment |

All multi-byte fields are little-endian. Loss detection uses sequence gaps.
Full field layout: [docs/protocol.md](docs/protocol.md).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full validation workflow
(lint, type checking, test suites, and CI job reproduction).

Run bare `make` to see the repo command menu, and use `make doctor` before your
first bootstrap if you want a quick prerequisite check.

Tests are organized in feature-based subdirectories under `apps/server/tests/`
mirroring source modules. See [docs/testing.md](docs/testing.md) for the full
layout, mapping rules, and how to add new tests.

### Visual snapshot tests

```bash
cd apps/ui
npx playwright install chromium   # first time only
npm run test:visual               # compare against baselines
npm run test:visual:update        # regenerate after intentional changes
npm run test:visual:audit         # run broader visual audit on purpose
```

Default snapshot coverage uses one intentional viewport (`laptop-light`) with a
deterministic demo mode (`?demo=1`). When you want broader visual coverage, run
the opt-in audit sweep for the full laptop/tablet light/dark matrix.
Baselines live in `apps/ui/tests/snapshots/`.

## Reports

Generate a PDF diagnostic report from a recorded run:

```bash
vibesensor-report path/to/metrics_run.jsonl
```

Reports adapt to available data — if speed or engine RPM references are missing,
order-specific sections are skipped with explicit reason text instead of
speculative labels. See [docs/run_schema_v2.md](docs/run_schema_v2.md) for the
run log format. Synthetic analysis scenarios live in
`apps/server/tests/test_support/`.

## Troubleshooting

- **Phone says "No internet"** — expected for offline AP; stay connected and
  open http://10.4.0.1
- **No clients visible** — verify ESP joined SSID, Pi UDP ports 9000/9001 open,
  server bound on 0.0.0.0:80 (or 8000 in dev)
- **High dropped frames** — reduce Wi-Fi contention, keep ESP close to Pi,
  check AP channel
- **Hotspot has no DHCP leases** — rerun `apps/server/scripts/hotspot_nmcli.sh`
- **Need config details** — check [apps/server/README.md](apps/server/README.md)
  and [firmware/esp/README.md](firmware/esp/README.md) for AP/firmware settings

## Developer Safeguards

`make setup` enables the versioned local hooks automatically. If you skipped
that bootstrap flow or want to re-enable them manually, run:

```bash
git config core.hooksPath .githooks
```

Current behavior:

- Hooks are safe to enable in normal development.
- The optional privacy guard only runs when `tools/privacy/privacy_guard.py` exists in the checkout.
- Use [CONTRIBUTING.md](CONTRIBUTING.md) for the supported local validation and CI reproduction workflow.

# VibeSensor

Portable, offline car vibration diagnostics using a Raspberry Pi and wireless accelerometer nodes.

## What Is VibeSensor?

VibeSensor is an end-to-end system that detects and localizes vehicle vibration issues — wheel imbalance, driveshaft rumble, engine harmonics — using low-cost hardware you can mount anywhere on a car. A Raspberry Pi runs as a standalone Wi-Fi access point, receives 400 Hz accelerometer streams from multiple ESP32 sensor nodes over UDP, performs real-time FFT analysis with automotive order tracking, and serves a mobile-friendly dashboard accessible from any phone or tablet. After a drive, it generates a professional PDF diagnostic report with findings, heatmaps, and evidence charts.

No internet connection required. No cloud. Everything runs locally on the Pi.

## Key Features

**Sensing & Analysis**
- Multi-sensor 3-axis accelerometer monitoring at 400 Hz (ADXL345)
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
- Ruff linting and TypeScript type checking enforced in CI
- Custom binary UDP protocol with sequence-based loss detection

## Units

- Raw sensor samples may contain acceleration values in g (for example `accel_x_g`, `accel_y_g`, `accel_z_g`) and related ingest-time/raw-spectrum amplitudes.
- Post-stop analysis outputs (persisted analysis summaries, findings metrics, report-template artifacts, and report-facing strength fields) are dB-only.
- The canonical vibration-strength definition is implemented in `libs/core/python/vibesensor_core/vibration_strength.py` via `vibration_strength_db_scalar()` and follows:
  - `20*log10((peak_band_rms_amp_g + eps) / (floor_amp_g + eps))`
  - `eps = max(1e-9, floor_amp_g * 0.05)`

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
  simulator/   Runnable simulator + websocket smoke tools
firmware/
  esp/         ESP32 firmware (PlatformIO, C++)
libs/
  core/        Pure domain logic (no IO/framework)
  shared/      Canonical contracts/schemas/constants
infra/
  pi-image/    Raspberry Pi image build pipeline
  ci/          CI helpers
docs/          Protocol spec, run schema, design language
hardware/      Bill of materials and wiring reference
examples/      Sample run data for report generation
tools/         Utilities (config checks, tests, support scripts)
artifacts/     Build/runtime artifacts (non-source)
```

Each component has its own README with setup instructions and details.

## Docs Index (source of truth)

- Setup & deployment: [README.md](README.md), [apps/server/README.md](apps/server/README.md), [firmware/esp/README.md](firmware/esp/README.md), [infra/pi-image/pi-gen/README.md](infra/pi-image/pi-gen/README.md)
- Updater architecture & policy: [apps/server/README.md](apps/server/README.md)
- Wire protocol and ports: [docs/protocol.md](docs/protocol.md)
- Run/report schema: [docs/run_schema_v2.md](docs/run_schema_v2.md)
- Report/design language: [docs/design_language.md](docs/design_language.md)
- AI guidance (canonical): [docs/ai/repo-map.md](docs/ai/repo-map.md), [.github/instructions/general.instructions.md](.github/instructions/general.instructions.md), [.github/copilot-instructions.md](.github/copilot-instructions.md)
- Historical snapshots/audits: [docs/test_coverage_audit.md](docs/test_coverage_audit.md), [docs/ai/progress.md](docs/ai/progress.md)

## Quick Start

### Docker (fastest)

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

### Native Python

```bash
pip install -e "./apps/server[dev]"
python tools/sync_ui_to_pi_public.py
vibesensor-server --config apps/server/config.dev.yaml
```

In another terminal:

```bash
vibesensor-sim --count 5 --server-host 127.0.0.1
```

Open http://localhost:8000.

The simulator supports interactive commands — type `help` to see options like
`list`, `set <sensor> profile <name>`, `pulse`, `pause`, `resume`.

## Deploying to Raspberry Pi

Both deployment modes target Raspberry Pi 3 A+ with Bookworm Lite.

### Mode A: Manual install

Flash official Raspberry Pi OS Lite, then on the Pi:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
sudo ./apps/server/scripts/install_pi.sh
sudo ./apps/server/scripts/hotspot_nmcli.sh
```

See [apps/server/README.md](apps/server/README.md) for configuration and uplink-update details.

### Mode B: Prebuilt image

Build on a Linux machine with Docker:

```bash
./infra/pi-image/pi-gen/build.sh
```

Flash the output image from `infra/pi-image/pi-gen/out/` and boot — no manual steps needed.

See [infra/pi-image/pi-gen/README.md](infra/pi-image/pi-gen/README.md) for details.

### Verification

Connect a phone to the `VibeSensor` Wi-Fi (default in `config.example.yaml` is
an open AP with empty PSK) and open http://10.4.0.1. Sensor nodes should appear
within seconds.

> Default AP credentials are for prototype use only. Change SSID/PSK before
> real-world deployment.

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

### Lint and format

```bash
ruff check apps/server/vibesensor apps/server/tests apps/simulator
ruff format --check apps/server/vibesensor apps/server/tests apps/simulator
```

### Tests

```bash
# Fast run (excludes browser tests)
pytest -q -m "not selenium" apps/server/tests

# With live progress and ETA
python3 tools/tests/pytest_progress.py -- -m "not selenium" apps/server/tests

# UI typecheck + build
cd apps/ui && npm run typecheck && npm run build
```

### Visual snapshot tests

```bash
cd apps/ui
npx playwright install chromium   # first time only
npm run test:visual               # compare against baselines
npm run test:visual:update        # regenerate after intentional changes
```

Screenshots are captured for 4 viewports (laptop-light, laptop-dark,
tablet-light, tablet-dark) using a deterministic demo mode (`?demo=1`).
Baselines live in `apps/ui/tests/snapshots/`.

## Reports

Generate a PDF diagnostic report from a recorded run:

```bash
vibesensor-report path/to/metrics_run.jsonl
```

Reports adapt to available data — if speed or engine RPM references are missing,
order-specific sections are skipped with explicit reason text instead of
speculative labels. See [docs/run_schema_v2.md](docs/run_schema_v2.md) for the
run log format and [examples/](examples/) for sample data.

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

Enable versioned local hooks (privacy guard + metadata checks):

```bash
git config core.hooksPath .githooks
```

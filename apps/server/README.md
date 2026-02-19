# Pi Server

FastAPI backend that ingests UDP accelerometer telemetry from ESP32 nodes,
performs real-time FFT signal processing, pushes live diagnostics over WebSocket,
and generates PDF diagnostic reports.

## Architecture

```
  ESP32 nodes ──► UDP 9000 ──► udp_data_rx.py ──► processing.py (FFT + metrics)
                                                         │
                  UDP 9001 ◄── udp_control_tx.py         ├──► ws_hub.py ──► Browser
                                                         │
                                                         ├──► metrics_log.py ──► JSONL + SQLite
                                                         │
                                                         └──► live_diagnostics.py (events)
```

Key modules in `vibesensor/`:

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI application entry point and lifecycle |
| `api.py` | HTTP + WebSocket endpoint definitions |
| `protocol.py` | UDP wire protocol parser (HELLO, DATA, CMD, ACK) |
| `processing.py` | FFT, waveform, RMS/P2P, peak detection, spike filtering |
| `metrics_log.py` | Run recording to JSONL with auto-start/stop on silence |
| `history_db.py` | SQLite storage for run metadata and analysis results |
| `live_diagnostics.py` | Real-time vibration event detection and severity tracking |
| `ws_hub.py` | WebSocket connection management and broadcast |
| `udp_data_rx.py` | UDP data listener (port 9000) |
| `udp_control_tx.py` | UDP control sender (port 9001, identify command) |
| `report_pdf.py` | PDF report generation (A4 landscape, workshop handout format) |
| `report_analysis.py` | Post-run analysis engine (findings, order matching) |
| `report_i18n.py` | Internationalization strings (EN, NL) |
| `config.py` | YAML configuration loader with defaults |
| `registry.py` | Connected client registry |
| `gps_speed.py` | GPSD client for speed input |
| `hotspot_self_heal.py` | Wi-Fi AP health monitoring and auto-recovery |
| `analysis_settings.py` | Vehicle parameter defaults and frequency band math |
| `settings_store.py` | Persistent car profiles and sensor settings |
| `car_library.py` | Vehicle database for car setup wizard |
| `locations.py` | Canonical sensor location codes |
| `constants.py` | Shared physical and analysis constants |

## Setup

### Local development

```bash
cd apps/server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m vibesensor.app --config config.dev.yaml
```

### Docker

From the repository root:

```bash
docker compose up --build
```

This runs the FastAPI/UDP server only — no AP/hotspot configuration.

## Configuration

Configuration is loaded from YAML. See `config.example.yaml` for all options.

| Section | Key fields |
|---------|------------|
| `server` | `host`, `port` (default 0.0.0.0:8000) |
| `udp` | `data_listen` (9000), `control_listen` (9001) |
| `processing` | `sample_rate_hz`, `fft_n`, `spectrum_max_hz`, `ui_push_hz` |
| `logging` | `log_metrics`, `metrics_log_path`, `sensor_model` |
| `storage` | `clients_json_path` |
| `gps` | `gps_enabled`, `gps_speed_only` |
| `ap` | `ssid`, `psk`, `ip`, `channel`, `self_heal` |

Development configs (`config.dev.yaml`, `config.docker.yaml`) override only
paths — all other values use built-in defaults.

Default runtime files (when using built-in defaults or `config.example.yaml`):
- `logging.metrics_log_path` → `apps/server/data/metrics.jsonl` (optional, disabled by default)
- `logging.history_db_path` → `apps/server/data/history.db`
- `storage.clients_json_path` → `apps/server/data/clients.json`
- `ap.self_heal.state_file` → `apps/server/data/hotspot-self-heal-state.json`

## Files

```
apps/server/
├── pyproject.toml           Package metadata and dependencies
├── config.yaml              Active Pi configuration
├── config.dev.yaml          Local dev overrides (repo-relative paths)
├── config.docker.yaml       Docker overrides
├── config.example.yaml      Deployment template (all options documented)
├── wifi-secrets.example.env Template for uplink Wi-Fi credentials
├── public/                  Built UI static assets (served by FastAPI)
├── data/                    Runtime data (settings.json)
├── scripts/
│   ├── install_pi.sh        Install deps, venv, systemd units
│   ├── hotspot_nmcli.sh     Idempotent AP setup via NetworkManager
│   └── hotspot_self_heal.py Self-heal entry point (also in vibesensor/)
├── systemd/
│   ├── vibesensor.service
│   ├── vibesensor-hotspot.service
│   ├── vibesensor-hotspot-self-heal.service
│   └── vibesensor-hotspot-self-heal.timer
├── tests/                   pytest suite (391+ tests)
└── vibesensor/              Application package
```

## Uplink Update Before Hotspot

The hotspot script can briefly join an existing Wi-Fi network to pull updates
before switching to AP mode.

1. Copy `wifi-secrets.example.env` to `/etc/vibesensor/wifi-secrets.env`
2. Set `WIFI_UPLINK_SSID` and `WIFI_UPLINK_PSK`
3. Restrict permissions: `chmod 600 /etc/vibesensor/wifi-secrets.env`

Behavior: scan for uplink SSID (up to 10 s) → connect and wait for update →
disconnect → start hotspot. If SSID not found, start hotspot directly.

## API Reference

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Server health check |

### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clients` | List connected sensors |
| GET | `/api/client-locations` | Available location codes |
| POST | `/api/clients/{id}/rename` | Rename a sensor |
| POST | `/api/clients/{id}/identify` | Trigger LED blink |
| POST | `/api/clients/{id}/location` | Set sensor location |
| DELETE | `/api/clients/{id}` | Remove a client |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings` | Current settings |
| GET | `/api/settings/cars` | List car profiles |
| POST | `/api/settings/cars` | Create car profile |
| PUT | `/api/settings/cars/{id}` | Update car profile |
| DELETE | `/api/settings/cars/{id}` | Delete car profile |
| POST | `/api/settings/cars/active` | Set active car |
| GET | `/api/settings/speed-source` | Speed source config |
| POST | `/api/settings/speed-source` | Update speed source |
| GET | `/api/settings/sensors` | Sensor metadata |
| POST | `/api/settings/sensors/{mac}` | Update sensor metadata |
| DELETE | `/api/settings/sensors/{mac}` | Delete sensor metadata |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analysis-settings` | Current analysis parameters |
| POST | `/api/analysis-settings` | Update analysis parameters |
| GET | `/api/speed-override` | Current speed override |
| POST | `/api/speed-override` | Set manual speed |

### History & Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/history` | List recorded runs |
| GET | `/api/history/{id}` | Run details |
| GET | `/api/history/{id}/insights` | Analysis findings |
| GET | `/api/history/{id}/report.pdf` | Download PDF report |
| GET | `/api/history/{id}/export` | Download raw JSONL data |
| DELETE | `/api/history/{id}` | Delete a run |

### Recording

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/logging/status` | Recording state |
| POST | `/api/logging/start` | Start recording |
| POST | `/api/logging/stop` | Stop recording |

### Car Library

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/car-library` | Full vehicle database |
| GET | `/api/car-library/brands` | Available brands |
| GET | `/api/car-library/types` | Body types for a brand |
| GET | `/api/car-library/models` | Models for brand + type |

### Debug

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/debug/spectrum/{id}` | Detailed FFT debug info |
| GET | `/api/debug/raw-samples/{id}` | Raw time-domain samples |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws` | Live spectrum, client list, diagnostics, speed |

## Reports

Generate a PDF from a saved run:

```bash
vibesensor-report path/to/metrics_run.jsonl
```

Optional summary JSON output:

```bash
vibesensor-report path/to/run.jsonl --output report.pdf --summary-json summary.json
```

## Testing

```bash
# Fast run (excludes browser tests)
pytest -q -m "not selenium" apps/server/tests

# With live progress and ETA
python3 tools/tests/pytest_progress.py -- -m "not selenium" apps/server/tests
```

Test markers:
- `selenium` — browser-based UI tests (require Selenium + Chrome)
- `long_sim` — longer simulated-run tests (>20 s)

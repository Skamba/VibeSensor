# Pi Server

This package runs the local FastAPI + WebSocket server on Raspberry Pi and ingests UDP telemetry from ESP32 vibration nodes.

## Files

- `config.yaml`: active configuration
- `config.example.yaml`: template for deployments
- `scripts/hotspot_nmcli.sh`: idempotent AP setup using NetworkManager shared mode
- `scripts/install_pi.sh`: install deps, venv, and systemd unit
- `scripts/run_dev.sh`: local dev run with built-in simulator

## Local run

```bash
cd pi
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m vibesensor.app --config config.yaml
```

## API

- `GET /api/clients`
- `POST /api/clients/{client_id}/rename`
- `POST /api/clients/{client_id}/identify`
- `WS /ws`



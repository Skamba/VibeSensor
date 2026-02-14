# Pi Server

This package runs the local FastAPI + WebSocket server on Raspberry Pi and
ingests UDP telemetry from ESP32 vibration nodes.

## Files

- `config.yaml`: active configuration
- `config.dev.yaml`: local development config (repo-relative paths)
- `config.example.yaml`: template for deployments
- `wifi-secrets.example.env`: template for uplink Wi-Fi + git update settings
- `scripts/hotspot_nmcli.sh`: idempotent AP setup using NetworkManager shared mode
- `scripts/install_pi.sh`: install deps, venv, and systemd unit
- `scripts/run_dev.sh`: local dev run with built-in simulator

## Uplink Update Before Hotspot

The hotspot script can briefly join an existing Wi-Fi network, update this
repo, then switch back to AP mode.

1. Copy `wifi-secrets.example.env` to `/etc/vibesensor/wifi-secrets.env`.
2. Set `WIFI_UPLINK_SSID` and `WIFI_UPLINK_PSK`.
3. Keep permissions strict: `chmod 600 /etc/vibesensor/wifi-secrets.env`.

Behavior in `scripts/hotspot_nmcli.sh`:

- Scan for the uplink SSID for up to 10 seconds (configurable).
- If found, connect and wait for git update commands to finish.
- Disconnect uplink and create/start the hotspot.
- If SSID is not found within timeout, skip uplink and start hotspot directly.

## Local run

```bash
cd pi
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m vibesensor.app --config config.dev.yaml
```

## API

- `GET /api/clients`
- `POST /api/clients/{client_id}/rename`
- `POST /api/clients/{client_id}/identify`
- `WS /ws`

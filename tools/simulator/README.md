# Simulator

Spawns fake ESP32 sensor clients for testing VibeSensor without physical
hardware. Useful for local development, CI smoke tests, and reproducing
specific vibration scenarios.

`sim_sender.py` sends:

- HELLO packets every 2 seconds
- DATA frames at 800 Hz sample rate (200 samples per UDP frame)
- ACK for identify commands
- Deterministic MAC-style client IDs (shown in `list` output)
- Distinct vibration profiles per simulated sensor (`engine_idle`, `wheel_imbalance`, `rear_body`, `rough_road`)
- Road-scene behavior by default:
  - sometimes quiet (near no vibration)
  - sometimes one active sensor
  - sometimes all sensors active together
- Optional interactive CLI to modify profiles/amplitude/noise live

## Run

```bash
python tools/simulator/sim_sender.py --count 5 --server-host 127.0.0.1
```

With default settings and a TTY, interactive mode is enabled. You can keep this running while using the web UI.
Targets in interactive commands can be client name, hex `id`, or colon-form MAC address.

Common commands:

```text
help
list
profiles
set front-left profile rough_road
set all amp 1.25
set rear noise 1.8
pulse front-right 2.0
pause rear
resume rear
quit
```

Useful options:

- `--names front-left,front-right,rear-left,rear-right,trunk`
- `--duration 20` to auto-stop
- `--server-data-port 9000 --server-control-port 9001`
- `--interactive` force CLI mode
- `--no-interactive` disable CLI mode

## Scenarios

Deterministic fault scenarios for reproducible testing:

```bash
python tools/simulator/sim_sender.py \
  --server-host 127.0.0.1 \
  --count 5 \
  --names front-left,front-right,rear-left,rear-right,trunk \
  --scenario one-wheel-mild \
  --fault-wheel front-right \
  --speed-kmh 100 \
  --duration 40 \
  --no-interactive
```

This runs one slight wheel-order fault on the selected wheel while keeping other
sensors mostly quiet, so the report should localize to that wheel.

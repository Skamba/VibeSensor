# Simulator

`sim_sender.py` spawns multiple fake ESP32 clients that send:

- HELLO packets every 2 seconds
- DATA frames at 800 Hz sample rate (200 samples per UDP frame)
- ACK for identify commands
- Distinct vibration profiles per simulated sensor (`engine_idle`, `wheel_imbalance`, `rear_body`, `rough_road`)
- Road-scene behavior by default:
  - sometimes quiet (near no vibration)
  - sometimes one active sensor
  - sometimes all sensors active together
- Optional interactive CLI to modify profiles/amplitude/noise live

## Run

```bash
python tools/simulator/sim_sender.py --count 3 --server-host 127.0.0.1
```

With default settings and a TTY, interactive mode is enabled. You can keep this running while using the web UI.

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

- `--names front-left,front-right,rear`
- `--duration 20` to auto-stop
- `--server-data-port 9000 --server-control-port 9001`
- `--interactive` force CLI mode
- `--no-interactive` disable CLI mode

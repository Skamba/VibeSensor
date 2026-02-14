# Simulator

`sim_sender.py` spawns multiple fake ESP32 clients that send:

- HELLO packets every 2 seconds
- DATA frames at 800 Hz sample rate (200 samples per UDP frame)
- ACK for identify commands

## Run

```bash
python tools/simulator/sim_sender.py --count 3 --server-host 127.0.0.1
```

Useful options:

- `--names front-left,front-right,rear`
- `--duration 20` to auto-stop
- `--server-data-port 9000 --server-control-port 9001`


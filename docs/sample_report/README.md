# Sample PDF Report

This folder contains a sample VibeSensor diagnostic PDF report generated from a
complex simulator run.

## Run Parameters

| Parameter | Value |
|-----------|-------|
| Sensors | 4 (front-left, front-right, rear-left, rear-right) |
| Duration | 60 seconds |
| Scenario | `one-wheel-mild` (deterministic single-wheel fault) |
| Fault wheel | front-left |
| Speed override | 80 km/h |

## Report Highlights

- **Suspected source:** Wheel / Tire
- **Inspect first:** Front-Left
- **Dominant evidence:** 2× and 1× wheel-order peaks at 80–90 km/h
- **Dominance ratio:** 3.25× over the next location (front-right)
- **Pages:** 3 (summary, evidence chain, inspection path)

## How to Regenerate

```bash
# 1. Build UI and start server
python tools/build_ui_static.py
vibesensor-server --config apps/server/config.dev.yaml &

# 2. Start a recording, run the simulator, then stop
curl -X POST http://127.0.0.1:8000/api/recording/start
vibesensor-sim \
  --count 4 \
  --names "front-left,front-right,rear-left,rear-right" \
  --scenario one-wheel-mild \
  --fault-wheel front-left \
  --duration 60 \
  --speed-kmh 80 \
  --no-auto-server \
  --no-interactive
curl -X POST http://127.0.0.1:8000/api/recording/stop

# 3. Wait for analysis and download the PDF
RUN_ID=$(curl -s http://127.0.0.1:8000/api/history | python3 -c \
  "import json,sys; runs=json.load(sys.stdin)['runs']; print(runs[0]['run_id'])")
curl "http://127.0.0.1:8000/api/history/$RUN_ID/report.pdf" \
  -o docs/sample_report/simulator_run_report.pdf
```

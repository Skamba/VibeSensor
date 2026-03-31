# Sample PDF Report — Complex Simulator Run

This directory contains a sample diagnostic PDF report generated from a full
120-second simulator run using four wheel sensors.

## Scenario

| Parameter | Value |
|---|---|
| Scenario | `one-wheel-mild` — single wheel imbalance fault |
| Fault wheel | FL (front-left) |
| Sensors | 4 (FL, FR, RL, RR) mapped to all four wheel positions |
| Speed | 80 km/h constant (manual override) |
| Duration | ~145 s recorded, 120 s simulator run |
| Sample count | 1,934 vibration feature samples |
| Car profile | BMW 3 Series (F30, 2012–2019), Sedan |

## Analysis result

The server correctly identified the injected fault:

| Field | Result |
|---|---|
| Top suspected source | `wheel/tire` |
| Strongest location | **Front Left** |
| Confidence | 65.4 % |
| Dominance ratio | 3.26× (FL vs all other sensors) |
| Speed band | 80–90 km/h |
| Alternative location | front_right |

## Files

- `complex_sim_run_report.pdf` — generated PDF report (4 pages)

## Regenerating

To regenerate this report from scratch:

```bash
# 1. Start the server
vibesensor-server --config apps/server/config.dev.yaml &

# 2. Configure sensors and car profile via API, then start recording
curl -X POST http://127.0.0.1:8000/api/recording/start

# 3. Run the simulator
vibesensor-sim \
  --count 4 --names FL,FR,RL,RR \
  --duration 120 --speed-kmh 80 \
  --scenario one-wheel-mild --fault-wheel FL \
  --server-host 127.0.0.1 --server-http-port 8000 \
  --no-interactive --no-auto-server

# 4. Stop recording and wait for analysis
curl -X POST http://127.0.0.1:8000/api/recording/stop

# 5. Download the PDF
curl "http://127.0.0.1:8000/api/history/<run_id>/report.pdf?lang=en" -o report.pdf
```

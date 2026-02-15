# VibeSensor Prototype

End-to-end prototype for local/offline car vibration sensing:

- Raspberry Pi 3A+ runs as offline Wi-Fi AP and telemetry server
- Multiple ESP32 (M5Stack ATOM Lite) clients stream ADXL345 samples (800 Hz)
- Pi computes live waveform + FFT spectrum + metrics and serves a mobile-friendly web UI
- Multi-client registry supports naming and identify blink command
- Dev simulator provides reproducible CI/local testing without Pi/ESP hardware
- Diagnostics/report pipeline uses reproducible run logs (`.jsonl`) with explicit references

Hardware list and wiring notes: `hardware/README.md`

## Repository Layout

```
.
├─ pi/
│  ├─ pyproject.toml
│  ├─ config.yaml
│  ├─ config.dev.yaml
│  ├─ config.example.yaml
│  ├─ public/
│  ├─ scripts/
│  ├─ systemd/
│  └─ vibesensor/
├─ esp/
├─ tools/simulator/
└─ .github/workflows/ci.yml
```

## Quickstart (Any Dev Machine)

```bash
cd pi
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m vibesensor.app --config config.dev.yaml
```

In another terminal:

```bash
python tools/simulator/sim_sender.py --count 5 --server-host 127.0.0.1
```

The simulator stays running while you use the UI and supports interactive commands:
`help`, `list`, `set`, `pulse`, `pause`, `resume`, `quit`.
In the dashboard Vehicle Settings panel, tire settings are split into 3 fields
(width mm / aspect % / rim inches), with defaults for a 640i setup: `285 / 30 / R21`.

Open:

- `http://localhost:8000`

## Diagnostics v2 (Schema + Reporting)

Run logs are written as `metrics_*.jsonl` records with required metadata and
required per-sample fields (`t_s`, `speed_kmh`, `accel_x_g/y_g/z_g`).

Processing uses explicit sensor scaling (`accel_scale_g_per_lsb`) and removes DC
before vibration RMS/P2P and FFT metrics, so reported amplitudes represent
vibration content instead of gravity offset.

Schema reference:

- `docs/run_schema_v2.md`

Generate a report from a saved run:

```bash
vibesensor-report pi/data/metrics_20260215_120000.jsonl
```

If speed or sample-rate references are missing, the report degrades gracefully:

- speed-binned and wheel-order sections are skipped with explicit reason text
- findings include `reference missing` entries instead of speculative order labels

When references are available, report findings use order tracking over changing
speed via per-sample matched peaks (`top_peaks`) instead of fixed-Hz clustering.

## Run With Docker (Single Entrypoint)

Use Docker Compose for both development and local runtime. This path does not
run Raspberry Pi AP/hotspot setup.

Compose starts two services:

- `vibesensor-server` (Python): UDP ingest + processing + `/api` + `/ws`
- `vibesensor-web` (nginx): serves built UI and proxies `/api` + `/ws` to server

```bash
docker compose up --build
```

Then open:

- `http://localhost:8000` (served by nginx)

To stream test data from host:

```bash
python tools/simulator/sim_sender.py --count 5 --server-host 127.0.0.1
```

Stop container:

```bash
docker compose down
```

## Two Ways To Deploy

Both deployment modes use idempotent scripts:

- `pi/scripts/install_pi.sh`
- `pi/scripts/hotspot_nmcli.sh`

### Mode A: Manual install on stock Raspberry Pi OS (Bookworm Lite)

Flash official Raspberry Pi OS Lite to SD card, then run on the Pi:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
sudo ./pi/scripts/install_pi.sh
# Optional: configure uplink update credentials (kept out of git)
sudo cp pi/wifi-secrets.example.env /etc/vibesensor/wifi-secrets.env
sudo nano /etc/vibesensor/wifi-secrets.env
sudo chmod 600 /etc/vibesensor/wifi-secrets.env
sudo ./pi/scripts/hotspot_nmcli.sh
sudo systemctl status vibesensor
```

`pi/scripts/hotspot_nmcli.sh` scans for the configured uplink Wi-Fi for up to
10 seconds. If found, it waits for git update activity to complete, then
disconnects and starts the hotspot. If not found, it starts the hotspot
immediately.

### Mode B: Prebuilt custom image (pi-gen + Docker, Raspberry Pi 3 A+ target)

Run on a Linux build machine:

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
./image/pi-gen/build.sh   # outputs an .img in image/pi-gen/out/
```

Then flash the produced `.img` (or `.img.xz`/`.zip` artifact) using Raspberry Pi Imager.  
After first boot, no manual install steps are required; hotspot + server are already enabled.

See image build notes: `image/pi-gen/README.md`

## Verification (Both Modes)

Default AP credentials in this repo are for local prototype use only. Change
SSID/PSK before any real-world deployment.

- Phone: connect to SSID `VibeSensor` (PSK `vibesensor123`)
- Open: `http://192.168.4.1:8000`
- You should see the UI, and clients should appear within a few seconds.

## ESP Setup (PlatformIO)

```bash
cd esp
pio run -t upload
pio device monitor
```

Edit `esp/src/main.cpp` before flashing:

- `kWifiSsid`, `kWifiPsk`
- `kClientName`
- `kServerIp`
- ADXL345 I2C settings (`kI2cSdaPin`, `kI2cSclPin`, `kAdxlI2cAddr`)

## Protocol Summary

UDP datagrams:

- HELLO (`type=1`) client identity, name, control port
- DATA (`type=2`) sample frames with sequence numbers
- CMD (`type=3`) server command (`identify`)
- ACK (`type=4`) command acknowledgment

Loss detection uses sequence gaps on the Pi (`frames_dropped` per client).
Canonical field/size reference: `docs/protocol.md`.

## Troubleshooting

- Phone says “No internet”:
  - expected for offline AP; stay connected and open `http://192.168.4.1:8000`
- No clients visible:
  - verify ESP joined SSID, Pi UDP ports `9000/9001` open locally
  - verify server is bound on `0.0.0.0:8000`
- High dropped frames:
  - reduce Wi-Fi contention
  - keep ESP close to Pi AP
  - check AP channel and frame size
- Hotspot has no DHCP leases:
  - rerun `pi/scripts/hotspot_nmcli.sh` (it configures NetworkManager dnsmasq mode)

## Developer Safeguards

To enable versioned local hooks (privacy guard + metadata checks):

```bash
git config core.hooksPath .githooks
git config user.email "8420201+Skamba@users.noreply.github.com"
```

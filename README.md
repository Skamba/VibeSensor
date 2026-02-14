# VibeSensor Prototype

End-to-end prototype for local/offline car vibration sensing:

- Raspberry Pi 3A+ runs as offline Wi-Fi AP and telemetry server
- Multiple ESP32 (LOLIN C3 Mini) clients stream ADXL345 samples (800 Hz)
- Pi computes live waveform + FFT spectrum + metrics and serves a mobile-friendly web UI
- Multi-client registry supports naming and identify blink command
- Dev simulator provides reproducible CI/local testing without Pi/ESP hardware

## Repository Layout

```
.
├─ pi/
│  ├─ pyproject.toml
│  ├─ config.yaml
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
python -m vibesensor.app --config config.yaml
```

In another terminal:

```bash
python tools/simulator/sim_sender.py --count 3 --server-host 127.0.0.1
```

The simulator stays running while you use the UI and supports interactive commands (`help`, `list`, `set`, `pulse`, `pause`, `resume`, `quit`).
In the dashboard Vehicle Settings panel, tire settings are split into 3 fields (width mm / aspect % / rim inches), with defaults for a 640i setup: `285 / 30 / R21`.

Open:

- `http://localhost:8000`

## Two Ways To Deploy

Both deployment modes use idempotent scripts:

- `pi/scripts/install_pi.sh`
- `pi/scripts/hotspot_nmcli.sh`

### Mode A: Manual install on stock Raspberry Pi OS (Bookworm Lite)

Flash official Raspberry Pi OS Lite to SD card, then run on the Pi:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/<MY_GITHUB_USER>/VibeSensor.git
cd VibeSensor
sudo ./pi/scripts/install_pi.sh
sudo ./pi/scripts/hotspot_nmcli.sh
sudo systemctl status vibesensor
```

### Mode B: Prebuilt custom image (pi-gen + Docker)

Run on a Linux build machine:

```bash
git clone https://github.com/<MY_GITHUB_USER>/VibeSensor.git
cd VibeSensor
./image/pi-gen/build.sh   # outputs an .img in image/pi-gen/out/
```

Then flash the produced `.img` (or `.img.xz`/`.zip` artifact) using Raspberry Pi Imager.  
After first boot, no manual install steps are required; hotspot + server are already enabled.

See image build notes: `image/pi-gen/README.md`

## Verification (Both Modes)

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
- ADXL345 SPI pins (`kSpiSckPin`, `kSpiMisoPin`, `kSpiMosiPin`, `kAdxlCsPin`)

## Protocol Summary

UDP datagrams:

- HELLO (`type=1`) client identity, name, control port
- DATA (`type=2`) sample frames with sequence numbers
- CMD (`type=3`) server command (`identify`)
- ACK (`type=4`) command acknowledgment

Loss detection uses sequence gaps on the Pi (`frames_dropped` per client).

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


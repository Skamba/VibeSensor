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
│  └─ vibesenser/
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
python -m vibesenser.app --config config.yaml
```

In another terminal:

```bash
python tools/simulator/sim_sender.py --count 3 --server-host 127.0.0.1
```

Open:

- `http://localhost:8000`

## Pi Setup

### 1) Configure AP hotspot (idempotent)

```bash
cd pi
chmod +x scripts/hotspot_nmcli.sh
./scripts/hotspot_nmcli.sh
```

This uses `nmcli` with:

- mode `ap`
- band `bg`
- WPA2-PSK
- `ipv4.method shared` for DHCP/NAT
- static AP IP from config (default `192.168.4.1/24`)

### 2) Install server service

```bash
cd pi
chmod +x scripts/install_pi.sh
./scripts/install_pi.sh
```

Then from a phone connected to the AP:

- `http://192.168.4.1:8000`

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


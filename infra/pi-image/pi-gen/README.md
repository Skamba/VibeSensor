# Prebuilt Raspberry Pi Image

Builds a custom Raspberry Pi OS Lite (Bookworm) image with VibeSensor
pre-installed. After flashing to an SD card and booting, the Pi is ready to use
with no manual setup.

## Prerequisites

- Linux build machine (or WSL2)
- Docker
- git, rsync
- ~20 minutes build time (depends on cache and network)

## Build

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
./infra/pi-image/pi-gen/build.sh
```

Output image: `infra/pi-image/pi-gen/out/vibesensor-rpi3a-plus-bookworm-lite.img`

Default SSH credentials in generated images:
- user: `pi`
- password: `vibesensor`

Override at build time if needed:

```bash
VS_FIRST_USER_NAME=pi VS_FIRST_USER_PASS='your-password' ./infra/pi-image/pi-gen/build.sh
```

## What's Included

The image contains:

- Raspberry Pi OS Lite (Bookworm, arm64)
- VibeSensor Python server with all dependencies
- Built web UI (served from `apps/server/public/`)
- systemd services enabled at boot:
  - `vibesensor.service` — FastAPI server
  - `vibesensor-hotspot.service` — Wi-Fi AP setup via NetworkManager
  - `vibesensor-hotspot-self-heal.timer` — periodic AP health check (every 2 min)

## Flash

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to write the
`.img` file (or `.img.xz`/`.zip` artifact) to an SD card.

Insert the card into a Raspberry Pi 3 A+ and power on. The hotspot and server
start automatically on first boot.

## How It Works

`build.sh` uses [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker to
produce the image. It adds a custom stage that:

1. Copies the VibeSensor repository into `/opt/VibeSensor`
2. Runs `apps/server/scripts/install_pi.sh` (deps, venv, systemd units)
3. Enables the hotspot and self-heal services

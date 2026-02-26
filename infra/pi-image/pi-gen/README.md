# Prebuilt Raspberry Pi Image

Builds a custom Raspberry Pi OS Lite (Bookworm) image with VibeSensor
pre-installed. After flashing to an SD card and booting, the Pi is ready to use
with no manual setup.

## Prerequisites

- Linux build machine (or WSL2)
- Docker
- git, rsync
- ~20 minutes build time (depends on cache and network)
- For best x86/WSL performance, keep the repo on the Linux filesystem (for example `/home/...`), not on a Windows-mounted path.

## Build

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
./infra/pi-image/pi-gen/build.sh
```

Output image: `infra/pi-image/pi-gen/out/vibesensor-rpi3a-plus-bookworm-lite.img`

Useful build flags for faster x86 iteration:

```bash
# skip expensive post-build mount/chroot validation
FAST=1 ./infra/pi-image/pi-gen/build.sh

# or explicitly disable validation
VALIDATE=0 ./infra/pi-image/pi-gen/build.sh

# force UI rebuild (default is hash-based incremental)
FORCE_UI_BUILD=1 ./infra/pi-image/pi-gen/build.sh

# optional artifact copy destination (disabled by default)
COPY_ARTIFACT_DIR=/tmp/pi-images ./infra/pi-image/pi-gen/build.sh

# optional: write first-boot SSH diagnostics to /boot/ssh-debug.txt
SSH_FIRST_BOOT_DEBUG=1 ./infra/pi-image/pi-gen/build.sh
```

Default SSH credentials in generated images:
- user: `pi`
- password: `vibesensor`

SSH first-boot behavior:
- `openssh-server` is installed and `ssh.service` is enabled at image build time.
- Host keys are intentionally not pre-generated in the image; they are generated on-device at first boot.
- A systemd SSH drop-in ensures host keys are generated before `sshd` starts, so SSH is available on first boot without relying on timing.

Override at build time if needed:

```bash
VS_FIRST_USER_NAME=pi VS_FIRST_USER_PASS='your-password' ./infra/pi-image/pi-gen/build.sh
```

If you require key-only SSH, provision authorized keys during image customization and validate they exist; this repo defaults to password auth for recovery-oriented hotspot deployments.

## What's Included

The image contains:

- Raspberry Pi OS Lite (Bookworm, arm64)
- VibeSensor Python server with all dependencies
- Built web UI (served from `apps/server/public/`)
- Preloaded offline ESP build toolchain/packages for `m5stack_atom`
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

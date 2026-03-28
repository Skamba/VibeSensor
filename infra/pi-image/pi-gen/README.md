# Prebuilt Raspberry Pi Image

Builds a custom Raspberry Pi OS Lite (Trixie) image with VibeSensor
pre-installed. After flashing to an SD card and booting, the Pi is ready to use
with no manual setup.

## Prerequisites

- Linux build machine (or WSL2)
- Docker
- git, rsync
- `qemu-user` (provides host `qemu-arm` for current upstream `pi-gen`)
- `qemu-user-static` (used by VibeSensor's post-build image validator)
- ~20 minutes build time (depends on cache and network)
- For best x86/WSL performance, keep the repo on the Linux filesystem (for example `/home/...`), not on a Windows-mounted path.

On Debian/Ubuntu hosts you can install the image-build prerequisites with:

```bash
sudo apt-get update
sudo apt-get install -y docker.io git qemu-user qemu-user-static rsync xz-utils
```

On Ubuntu runners, `qemu-user-binfmt` conflicts with `qemu-user-static`, so use
`qemu-user` to provide `qemu-arm` instead.

## Build

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
./infra/pi-image/pi-gen/build.sh
```

Default (`BUILD_MODE=all`) runs:
1. app artifact build (UI + server wheel),
2. image build.

Split workflow (wheel-first):

```bash
# build app artifacts only (re-runnable, cacheable in CI)
BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh

# build image from previously built app artifacts
BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh
```

Standalone validation against an existing image artifact:

```bash
# validate the current artifact in infra/pi-image/pi-gen/out/
./infra/pi-image/pi-gen/validate-image.sh

# or validate a specific .img / .img.xz / .zip artifact
./infra/pi-image/pi-gen/validate-image.sh infra/pi-image/pi-gen/out/your-image.img.xz
```

Artifacts:
- app artifacts: `infra/pi-image/pi-gen/out/app-artifacts/`
- image: `infra/pi-image/pi-gen/out/vibesensor-rpi3a-plus-trixie-lite.img`

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

## Failure recovery

When `build.sh` fails, isolate which stage failed before retrying everything:

1. If the app artifact build failed, rerun just that stage:

   ```bash
   BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh
   ```

2. If the app artifacts are already good and the image stage failed, rerun only
   the image build:

   ```bash
   BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh
   ```

3. If the main build finished but the validator failed, rerun
   `validate-image.sh` directly against the existing artifact so you can debug
   validation separately from the build itself.
4. Use `FAST=1` or `VALIDATE=0` only to narrow down where the failure occurs;
   rerun with normal validation before trusting the artifact.
5. If the generated pi-gen workspace looks suspect, remove `.cache/pi-gen/` and
   rerun from a clean checkout state.
6. If first-boot SSH availability is the problem, rebuild with
   `SSH_FIRST_BOOT_DEBUG=1` so the image writes diagnostics to `/boot/ssh-debug.txt`.

## What's Included

The image contains:

- Raspberry Pi OS Lite (Trixie, armhf)
- VibeSensor Python server with all dependencies
- Built web UI (served from `apps/server/vibesensor/static/`)
- Preloaded offline ESP build toolchain/packages for `m5stack_atom`
- systemd services enabled at boot:
  - `vibesensor.service` — FastAPI server
  - `vibesensor-hotspot.service` — Wi-Fi AP setup via NetworkManager
  - `vibesensor-rfkill-unblock.service` — unblocks Wi-Fi before NetworkManager starts
  - `vibesensor-hotspot-self-heal.timer` — periodic AP health check (every 2 min)

## Flash

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to write the
`.img` file (or `.img.xz`/`.zip` artifact) to an SD card.

Insert the card into a Raspberry Pi 3 A+ and power on. The hotspot and server
start automatically on first boot.

## Weekly GitHub release builds

The repository also publishes an automated weekly Pi image snapshot through
GitHub Actions:

- workflow: [`.github/workflows/weekly-pi-image.yml`](../../../.github/workflows/weekly-pi-image.yml)
- triggers: weekly schedule plus manual `workflow_dispatch`
- release assets: compressed Pi image, checksum, and version metadata
- release retention: the workflow deletes older weekly Pi-image prereleases
  before publishing the newest snapshot, so GitHub Releases only shows the
  latest weekly Pi image entry

These weekly builds reuse the same `./infra/pi-image/pi-gen/build.sh` pipeline
documented above, so the GitHub Release artifact follows the same supported
image-build path as local builds.

## Pipeline layout

The pi-image pipeline now has three explicit ownership layers:

- `build.sh` — thin coordinator for `BUILD_MODE=app|image|all`
- `lib/*.sh` — focused host-side helpers for prerequisites, mirror selection,
  app artifact build, pi-gen repo prep, stage assembly, artifact selection, and
  validation helpers
- `templates/` — tracked stage/config source files copied into `.cache/pi-gen/`
  instead of being emitted as long heredocs from `build.sh`

`validate-image.sh` is the standalone mount/chroot/QEMU validator. `build.sh`
invokes it automatically when `VALIDATE=1`, and you can rerun it separately
against an already-built artifact.

During pi-gen repo preparation, the build also patches upstream:

- `export-image/prerun.sh` to size the boot partition at `1 GiB`. Current
  Raspberry Pi kernel/security updates overflow the stock `512 MiB` bootfs
  during export-image upgrades.
- `stage0/files/raspberrypi.gpg` to replace the stale armhf bootstrap keyring
  that still carries SHA-1 self-signatures in upstream `master`. Trixie
  debootstrap rejects that key on modern GnuPG policies, so VibeSensor vendors
  a known-good replacement until upstream ships the refreshed keyring.

## How It Works

`build.sh` still uses [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker
to produce the image. The current flow is:

1. build app artifacts (UI bundle + `vibesensor-*.whl`),
2. sync runtime repo + app artifacts into the tracked stage templates,
3. copy those templates into the generated `pi-gen` stage tree,
4. build an ARM wheelhouse and install the server from the prebuilt wheel (non-editable),
5. enable the hotspot and self-heal services,
6. run the standalone validator when post-build validation is enabled.

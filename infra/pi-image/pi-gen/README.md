# Prebuilt Raspberry Pi Image

Builds a custom Raspberry Pi OS Lite (Trixie) image with VibeSensor
pre-installed. After flashing to an SD card and booting, the Pi is ready to use
with no manual setup.

Two userlands are supported, chosen with `VS_PI_ARCH`:

- `armhf` (default): 32-bit Raspberry Pi OS, the image the weekly release publishes.
- `arm64`: 64-bit Raspberry Pi OS (64-bit kernel, `arm_64bit=1`), for comparing
  post-drive analysis speed and memory on the same Pi 3 A+. Built the same way;
  workflow artifact only.

```bash
VS_PI_ARCH=arm64 ./infra/pi-image/pi-gen/build.sh
VS_PI_ARCH=arm64 ./infra/pi-image/pi-gen/validate-image.sh   # validate an arm64 artifact
```

## Prerequisites

- Linux build machine (or WSL2)
- Docker
- git, rsync
- `qemu-user` (provides host `qemu-arm` for current upstream `pi-gen`; armhf builds)
- `qemu-user-static` (used by VibeSensor's post-build image validator:
  `qemu-arm-static` for armhf, `qemu-aarch64-static` for arm64 on a non-arm64 host;
  an aarch64 host validates an arm64 image natively)
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

ACT is not the supported local runner for Pi-image workflows. The GitHub
workflow `weekly-pi-image.yml` uses the
`ubuntu-24.04-arm` runner label, which is intentionally not mapped in the repo
`.actrc`. Use the local build and validation commands below for Pi-image
changes.

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

Successful validation now reports the embedded server Python version from the
built image and verifies that it satisfies the packaged-server floor declared in
`apps/server/pyproject.toml`.

Artifacts:
- app artifacts: `infra/pi-image/pi-gen/out/app-artifacts/` (the same for both arches)
- image: `infra/pi-image/pi-gen/out/image_<date>-vibesensor-rpi3a-plus-trixie-lite-vibesensor-lite.zip`
  (armhf) or `...-vibesensor-arm64-lite.zip` (arm64); the arch suffixes never match
  each other, so both can sit in `out/`
- image build metadata: `infra/pi-image/pi-gen/out/*.version.txt` (includes the
  validated embedded server Python version/floor when post-build validation runs)


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

Default access endpoints and SSH credentials in generated images:
- hotspot address: `10.4.0.1`
- HTTP UI and API: `http://10.4.0.1` (port `80` default); if the primary listener is unavailable, try `http://10.4.0.1:8000`
- captive portal: the hotspot's shared-mode dnsmasq (AP interface only) resolves the OS connectivity-probe hosts (Android `generate_204`, Apple `hotspot-detect.html`, Windows `connecttest.txt`, ...) to `10.4.0.1`, and the server redirects them to the UI, so phones open it after joining. `hotspot_nmcli.sh` writes `/etc/NetworkManager/dnsmasq-shared.d/vibesensor-captive-portal.conf` from `vibesensor_hotspot.py config`; `validate-image.sh` checks both. The Pi's own DNS is untouched, so Wi-Fi/USB uplink updates still reach the real hosts. Phones may still report "no internet"; users stay connected.
- user: `pi`
- password: `vibesensor`
- remote simulator quick run: `vibesensor-sim --count 5 --duration 60 --server-host 10.4.0.1 --server-http-port 80 --speed-kmh 0 --no-interactive --no-auto-server`
- use `--speed-kmh 0` when you only need UDP traffic or the Pi HTTP API is not answering; non-zero speed override performs an HTTP POST before streaming

SSH first-boot behavior:
- `openssh-server` is installed and `ssh.service` is enabled at image build time.
- Host keys are intentionally not pre-generated in the image; they are generated on-device at first boot.
- A systemd SSH drop-in ensures host keys are generated before `sshd` starts, so SSH is available on first boot without relying on timing.

Override at build time if needed:

```bash
VS_FIRST_USER_NAME=pi VS_FIRST_USER_PASS='your-password' ./infra/pi-image/pi-gen/build.sh
```

Password SSH with the standard default password is the accepted default, not a gap to fix: VibeSensor is a short-lived diagnosis tool without its own internet connection, so SSH is only reachable from the hotspot (or a temporary update uplink), and a known password keeps recovery simple. See [SECURITY.md](../../../SECURITY.md#ssh-access-accepted-risk). If you require key-only SSH, provision authorized keys during image customization and validate they exist.

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

- Raspberry Pi OS Lite (Trixie, armhf or arm64)
- A headless boot config (`templates/stage-vibesensor/01-headless-boot/`): `gpu_mem=16`,
  the KMS display driver (`dtoverlay=vc4-kms-v3d`, `max_framebuffers`) commented
  out, and `camera_auto_detect=0` in `config.txt`. VibeSensor never uses HDMI or a
  camera; on a Pi 3 A+ this leaves about 473 MB of RAM to Linux instead of 425 MB
  and shrinks the CMA pool from 256 MB to 64 MB. Image validation checks these
  settings and that the cut-down GPU firmware (`start_cd.elf`, `fixup_cd.dat`) is on
  the boot partition. To use a display for debugging, undo them in
  `/boot/firmware/config.txt` on the SD card.
- VibeSensor Python server with all dependencies, installed as A/B venv slot
  `apps/server/.venv/slots/<version>` (`.venv/current` points at it, and
  `.venv/bin`, `.venv/lib`, and `.venv/pyvenv.cfg` route through `current`), so
  OTA updates can install beside it and revert automatically
- Built web UI (served from `apps/server/vibesensor/static/`)
- Preloaded offline ESP build toolchain/packages for `m5stack_atom`
- systemd services enabled at boot:
  - `vibesensor.service` — FastAPI server. It does not wait for `network-online.target` (the car has no upstream network), so it starts beside NetworkManager and the hotspot rather than after them
  - `vibesensor-hotspot.service` — Wi-Fi AP setup via NetworkManager
  - `vibesensor-hotspot-self-heal.timer` — hotspot watchdog (every 2 min): reactivates `VibeSensor-AP`, then re-provisions via `vibesensor-hotspot.service`
  - `vibesensor-cloud-init-off.service` — cloud-init still provisions the first boot (Raspberry Pi Imager customisation); at the end of that boot this unit creates `/etc/cloud/cloud-init.disabled`, so later boots skip cloud-init's stages, which held up NetworkManager and the hotspot by several seconds. Image validation fails if the server waits for `network-online.target`, if the flag is baked into the image, or if the unit is not enabled
  - `vibesensor-privileged.socket` — root commands for the updater and Bluetooth OBD admin. `vibesensor.service` runs with `NoNewPrivileges=true`, so it cannot use sudo. Each connection runs `vibesensor-privileged@.service` as root, through the allowlist wrapper it names (`vibesensor_update_allowlist.sh`, `vibesensor_obd_admin.py`). There is no sudoers entry.
  - root units run only the root-owned helper copies in `/usr/local/lib/vibesensor` (installed from `apps/server/root-helpers/` by `install_systemd_units.sh`) under `/usr/bin/python3 -I`, never code from the service user's venv; image validation fails otherwise
  - `/usr/local/lib/vibesensor/root-side.sha256`, the root-side manifest `install_systemd_units.sh` writes last; image validation fails unless its digest equals the installed app's `ROOT_SIDE_DIGEST`
- A persistent system journal: `install_systemd_units.sh` installs `apps/server/systemd/vibesensor-journald.conf` as `/etc/systemd/journald.conf.d/90-vibesensor.conf` (`Storage=persistent`, at most 32 MB), overriding Raspberry Pi OS's RAM-only journal so logs survive a power cut; image validation checks it
- Bluetooth OBD support prerequisites:
  - `bluez` / `pi-bluetooth` userspace packages in the image
  - root-side helper `/usr/local/lib/vibesensor/vibesensor_obd_admin.py` (stdlib only), reached through `vibesensor-privileged.socket` so the local UI can scan/pair adapters without SSH

## Flash

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to write the
`.img` file (or `.img.xz`/`.zip` artifact) to an SD card.

Insert the card into a Raspberry Pi 3 A+ and power on. The hotspot and server
start automatically on first boot. Both arches use the same user, password,
hotspot and SSH defaults listed above.

On-device updates work on both: each server release carries a dependency
wheelhouse per userland, and the updater installs from the one matching its
Python (`linux_armv7l` on armhf, `linux_aarch64` on arm64). Releases published
before arm64 wheelhouses existed have none for arm64, and the updater refuses
them with "no dependency wheelhouse for this device".

## Weekly GitHub release builds

The repository publishes an automated weekly Pi image snapshot through GitHub
Actions:

- workflow: [`.github/workflows/weekly-pi-image.yml`](../../../.github/workflows/weekly-pi-image.yml)
- runner: GitHub-hosted `ubuntu-24.04-arm` (native ARM, no x64 emulation)
- triggers: weekly schedule (always publishes the armhf image) plus manual
  `workflow_dispatch`; manual runs only upload a workflow artifact unless the
  `publish` input is set (publishing requires `main` and `arch=armhf`)
- `arch` input (manual runs): `armhf` (default) or `arm64`. An arm64 run builds
  natively on the ARM runner (no QEMU in the chroot) and uploads
  `VibeSensor-<yy-mm-dd>-arm64.img.zip` as workflow artifact
  `pi-image-<yy-mm-dd>-arm64`; armhf runs upload `pi-image-<yy-mm-dd>-armhf`
- assets: compressed Pi image, checksum, and version metadata (with `arch=`),
  uploaded as a workflow artifact on every run
- release retention: publishing deletes the previous weekly Pi-image release
  first, so GitHub Releases only shows the latest weekly Pi image entry

The workflow runs the same `./infra/pi-image/pi-gen/build.sh` pipeline
documented above, so the published image follows the same supported
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

The build uses upstream [pi-gen](https://github.com/RPi-Distro/pi-gen) at the
commit pinned by `PI_GEN_REF` in `lib/common.sh`, not upstream `master`.
Upstream builds 64-bit images from its `arm64` branch (it hard-codes
`ARCH=arm64`, bootstraps from Debian and adds `arm_64bit=1`), so `VS_PI_ARCH=arm64`
pins the `arm64` branch commit that merged the armhf pin; bump both together
(`PI_GEN_REF=arm64` for a trial build). The
patches below match upstream files by exact text, so an unpinned `master` let
an upstream change (RPi-Distro/pi-gen#933) fail the scheduled weekly image on an
unchanged `main` (2026-09-21 and 09-28). To move to a newer pi-gen, run
`PI_GEN_REF=master BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh` (or a
manual weekly workflow run on a branch with the bumped pin), fix any patch that
no longer matches, then update the pinned SHA. `PI_GEN_REF` also accepts a
branch or another commit for one-off builds.

During pi-gen repo preparation, the build also patches upstream (the mirror,
Docker base image and keyring fixes apply to armhf only; the `arm64` branch
installs from Debian's mirrors and already uses the native `debian:trixie` base):

- `export-image/prerun.sh` to size the boot partition at `1 GiB`. Current
  Raspberry Pi kernel/security updates overflow the stock `512 MiB` bootfs
  during export-image upgrades.
- `build-docker.sh` to keep `x86_64` hosts on the upstream `i386/debian:trixie`
  base image but let `aarch64` hosts use the native `debian:trixie` image.
  GitHub-hosted ARM runners cannot resolve the upstream `i386/debian:trixie`
  manifest, so the ARM-hosted manual workflow needs the native Debian base.
- `stage0/files/raspberrypi.gpg` to replace the stale armhf bootstrap keyring
  that still carries SHA-1 self-signatures in upstream `master`. Trixie
  debootstrap rejects that key on modern GnuPG policies, so VibeSensor vendors
  a known-good replacement until upstream ships the refreshed keyring.

## How It Works

`build.sh` still uses [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker
(container `pigen_work` for armhf, `pigen_arm64_work` for arm64) to produce the
image. The current flow is:

1. build app artifacts (UI bundle + `vibesensor-*.whl`),
2. sync runtime repo + app artifacts into the tracked stage templates,
3. copy those templates into the generated `pi-gen` stage tree,
4. build an ARM wheelhouse (armhf: PyPI + piwheels; arm64: PyPI's aarch64 wheels),
   install the server from the prebuilt wheel (non-editable), and
   move the venv into its first A/B slot (`python -m vibesensor.updates.venv_slots adopt`),
5. run `install_systemd_units.sh` in the chroot: install the root-side helpers, render the
   server, hotspot, hotspot watchdog timer and privileged socket units, write the root-side
   stamp, and enable the units,
6. run the standalone validator when post-build validation is enabled.

# Yocto Raspberry Pi image build

This is the supported Raspberry Pi image pipeline for VibeSensor.

It replaces the legacy `pi-gen` path with a KAS-managed Yocto build targeting a
single universal 64-bit Raspberry Pi image:

- `MACHINE = "raspberrypi-armv8"`
- one flashable SD-card image for Raspberry Pi 3 / 4 / 5
- GitHub-hosted ARM runners for CI builds
- Yocto `styhead` branches so the image runtime carries Python `3.13.x`,
  matching the current backend requirement

## Layout

- `build.sh` — host-side entrypoint that prepares the UI bundle, `vibesensor`
  wheel + wheelhouse, firmware baseline cache, then launches KAS/BitBake.
- `kas/` — pinned KAS configurations and lockfile.
- `meta-vibesensor/` — custom Yocto layer containing the image recipe,
  packagegroup, runtime bundle recipe, and custom WIC layout.
- `validate-image.sh` — post-build image validator for the generated SD-card
  image artifact.

## Prerequisites

Recommended host:

- Linux ARM64 machine (`aarch64`) or GitHub-hosted `ubuntu-24.04-arm`
- `python3 >= 3.13`
- git, rsync, npm, python3, kas, bzip2, losetup/mount tools
- For local validation on non-ARM hosts: `qemu-aarch64-static`
- locale `en_US.UTF-8` generated on the host (`bitbake` will refuse to start
  without it)

Typical Ubuntu host packages:

```bash
sudo apt-get update
sudo apt-get install -y \
  bzip2 file gawk git iproute2 locales mount npm python3 python3-pip \
  qemu-user-static rsync sudo umount unzip wget xz-utils zstd
sudo locale-gen en_US.UTF-8
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
```

If `kas` is not packaged on your distro, install it with pipx or pip:

```bash
python3 -m pip install --user kas
```

## Build

```bash
./infra/pi-image/yocto/build.sh
```

Outputs land in `infra/pi-image/yocto/out/`:

- `image_<timestamp>-vibesensor-rpi-universal.wic.bz2`
- matching `.sha256`
- matching `.manifest.json`

The build wrapper performs these phases:

1. build the UI bundle
2. stage a trimmed runtime repo snapshot
3. build the `vibesensor` wheel and dependency wheelhouse
4. prefetch the firmware baseline cache when possible
5. run the Yocto/KAS build
6. validate the produced image artifact (unless `VALIDATE=0`)

## Validation only

```bash
./infra/pi-image/yocto/validate-image.sh \
  infra/pi-image/yocto/out/image_<timestamp>-vibesensor-rpi-universal.wic.bz2
```

## CI

Image CI is driven by:

- `.github/workflows/weekly-pi-image.yml`
- `.github/workflows/manual-pi-image-arm.yml`

Both workflows now run on GitHub-hosted ARM runners and call
`./infra/pi-image/yocto/build.sh`.

## Legacy pi-gen path

The old `infra/pi-image/pi-gen/` flow is retained only as deprecated migration
reference material. It is no longer the supported or CI-backed image build
path.

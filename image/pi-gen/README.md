# Prebuilt Image (Mode B, Raspberry Pi 3 A+)

Build machine commands:

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
./image/pi-gen/build.sh   # outputs an .img in image/pi-gen/out/
```

`build.sh` uses `pi-gen` in Docker, adds VibeSensor into the image, installs the server, and enables:

- `vibesensor.service`
- `vibesensor-hotspot.service`

Output image artifacts are written to:

- `image/pi-gen/out/`

The produced image name is `vibesensor-rpi3a-plus-bookworm-lite` and is intended for Raspberry Pi 3 A+.

After flashing the produced image and first boot, no manual install steps are required.

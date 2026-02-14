# Prebuilt Image (Mode B)

Build machine commands:

```bash
git clone https://github.com/<MY_GITHUB_USER>/VibeSensor.git
cd VibeSensor
./image/pi-gen/build.sh   # outputs an .img in image/pi-gen/out/
```

`build.sh` uses `pi-gen` in Docker, adds VibeSensor into the image, installs the server, and enables:

- `vibesensor.service`
- `vibesensor-hotspot.service`

Output image artifacts are written to:

- `image/pi-gen/out/`

After flashing the produced image and first boot, no manual install steps are required.


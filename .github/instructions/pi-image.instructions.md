---
applyTo: "infra/pi-image/**"
---
Pi image (`infra/pi-image/**`)
- `infra/pi-image/pi-gen/build.sh` stays a thin coordinator for `BUILD_MODE=app|image|all`; keep host-side helpers in `pi-gen/lib/`, tracked stage/config sources in `pi-gen/templates/`, and post-build validation in `pi-gen/validate-image.sh`.
- Preserve the wheel-first, offline-first image flow: build app artifacts first, bake required packages and tools into the image, and avoid changes that make hotspot bring-up depend on internet access or ad-hoc post-boot mutation.
- Do not move tracked stage/template content back into long heredocs or runtime-generated files when `pi-gen/templates/` already owns it.
- Validation: choose the narrowest existing path that matches the change — `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh` for packaged app artifact changes, `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh` for image-stage logic, and `./infra/pi-image/pi-gen/validate-image.sh [artifact]` to rerun image validation without rebuilding. Use full `BUILD_MODE=all` only when both layers changed.

---
applyTo: "infra/pi-image/**"
---
Pi image rules for `infra/pi-image`.

- `pi-gen/build.sh` stays a thin coordinator for `BUILD_MODE=app|image|all`. Host helpers belong in `pi-gen/lib/`, tracked stage/config sources in `pi-gen/templates/`, and post-build validation in `pi-gen/validate-image.sh`.
- Preserve the wheel-first, offline-first image flow: build app artifacts first, bake required packages/tools into the image, and keep hotspot bring-up independent of internet access or ad-hoc post-boot mutation.
- Do not move tracked stage/template content back into heredocs or runtime-generated files when `pi-gen/templates/` owns it.
- Validation: start with `make plan-validation`; use the narrowest path: `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh` for packaged app artifacts, `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh` for image-stage logic, and `./infra/pi-image/pi-gen/validate-image.sh [artifact]` for existing artifacts. Use `BUILD_MODE=all` only when both layers changed.

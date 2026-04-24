# Pi image agent guidance

Pi image-specific rules live in `../../.github/instructions/pi-image.instructions.md`.

Keep `pi-gen/build.sh` as a thin coordinator. Host-side helpers belong in `pi-gen/lib/`, tracked stage/config sources belong in `pi-gen/templates/`, and post-build validation belongs in `pi-gen/validate-image.sh`.

Preserve the wheel-first, offline-first image flow.

Default validation:
- `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh` for packaged app artifact changes.
- `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh` for image-stage logic.
- `./infra/pi-image/pi-gen/validate-image.sh [artifact]` to rerun validation against an existing image artifact.

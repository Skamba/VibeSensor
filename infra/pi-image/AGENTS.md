# Pi image agent guidance

- Pi image rules: `../../.github/instructions/pi-image.instructions.md`.
- Keep `pi-gen/build.sh` thin; helpers in `pi-gen/lib/`, tracked sources in `pi-gen/templates/`, validation in `pi-gen/validate-image.sh`.
- Preserve wheel-first, offline-first image behavior.
- Validation: `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh`, `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh`, or `./infra/pi-image/pi-gen/validate-image.sh [artifact]`.

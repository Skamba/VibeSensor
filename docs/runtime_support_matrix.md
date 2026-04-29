# Runtime Support Matrix

This file is the canonical human-readable Python and Node support-policy reference
for VibeSensor. Other setup and workflow docs should point here instead of
restating version policy inline.

## Current support matrix

| Environment / path | Supported Python policy | Supported Node policy | Current source-of-truth files and notes |
|---|---|---|---|
| Native development, local tooling, and simulator runs | Use the exact version from [`.python-version`](../.python-version) (`3.13.5` today). | Use the major version from [`.nvmrc`](../.nvmrc) (`22.x` today). | `make doctor` and `tools/dev/check_prerequisites.py` enforce these local expectations. This is the recommended path for backend work, local UI work, and local CI reproduction. |
| GitHub Actions CI and release builders | Use the same value from [`.python-version`](../.python-version). | Use the same value from [`.nvmrc`](../.nvmrc). | [`.github/actions/setup-python/action.yml`](../.github/actions/setup-python/action.yml) is the authoritative GitHub Actions Python setup path, and [`.github/actions/setup-backend/action.yml`](../.github/actions/setup-backend/action.yml) layers backend dependency installation on top of it. Workflows should use those local actions instead of calling `actions/setup-python` directly. |
| Docker / container build path | The runtime image tag must match [`.python-version`](../.python-version). | The UI build-stage and Docker dev-mode Node tags must match [`.nvmrc`](../.nvmrc). | [`apps/server/Dockerfile`](../apps/server/Dockerfile) and [`docker-compose.dev.yml`](../docker-compose.dev.yml) are the concrete container surfaces. `tools/dev/check_hygiene.py` rejects drift from the version files, and [`.github/dependabot.yml`](../.github/dependabot.yml) tracks Docker base-image updates from the repo root. |
| Installable backend package / wheel compatibility | The backend package declares a minimum of `>=3.13` in [`apps/server/pyproject.toml`](../apps/server/pyproject.toml). | Not applicable. | This is the compatibility floor for the packaged server and the current Pi delivery paths, not the exact native-dev or CI pin. Backend Ruff formatting/lint stays on this floor so the formatter preserves package-compatible 3.13 syntax, while backend mypy type checking follows the exact native-dev / CI Python minor from [`.python-version`](../.python-version) (`3.13` today) so type checking matches the active repo toolchain. |
| Manual Raspberry Pi install and on-device runtime | Support follows the Raspberry Pi OS Lite (Trixie) baseline and requires the installed `python3` to satisfy the packaged-server floor from [`apps/server/pyproject.toml`](../apps/server/pyproject.toml) (`>=3.13` today). | Not required on-device. | [`apps/server/scripts/install_pi.sh`](../apps/server/scripts/install_pi.sh) validates `python3` before creating the venv. Current stock Trixie ships Python `3.13.5`, so the Pi runtime now matches the exact native-dev / CI pin instead of relying on a newer upstream interpreter line. |
| Prebuilt Pi image build | Builders use [`.python-version`](../.python-version) while producing the app artifacts, and image validation reports the embedded distro-backed server Python runtime while checking it against the packaged-server floor from [`apps/server/pyproject.toml`](../apps/server/pyproject.toml). The resulting image still targets Raspberry Pi OS Lite (Trixie, armhf) with the same Python `3.13.5` line on-device. | Builders use [`.nvmrc`](../.nvmrc) for the UI build; Node is not required on-device after the image is built. | See [`infra/pi-image/pi-gen/README.md`](../infra/pi-image/pi-gen/README.md) plus the weekly/manual Pi-image workflows for the supported image-build path. |

## Ownership for future updates

When the supported Python or Node policy changes, update this matrix in the same
change set as the machine-readable source files it references.

1. If the native-dev / CI / Docker Python pin changes, update
   [`.python-version`](../.python-version) first, then update dependent
   Docker tags, [`.github/actions/setup-python/action.yml`](../.github/actions/setup-python/action.yml),
   [`.github/actions/setup-backend/action.yml`](../.github/actions/setup-backend/action.yml),
   the backend `tool.mypy.python_version` setting in [`apps/server/pyproject.toml`](../apps/server/pyproject.toml),
   and docs that point at the native pin.
2. If the native-dev / CI / Docker Node policy changes, update
   [`.nvmrc`](../.nvmrc) first, then update dependent Docker tags
   (including [`apps/server/Dockerfile`](../apps/server/Dockerfile) and
   [`docker-compose.dev.yml`](../docker-compose.dev.yml)), `setup-node` usage,
   and docs that point at the Node policy.
3. If backend package compatibility changes independently from the native pin,
   update [`apps/server/pyproject.toml`](../apps/server/pyproject.toml), the
   backend `tool.ruff.target-version` setting, the install/image helpers and
   docs that describe the packaged-server compatibility floor, and any
   Pi-runtime wording that depends on that floor.
4. If the supported Raspberry Pi OS or on-device runtime baseline changes,
   update this matrix plus the matching deployment/image docs in
   [`README.md`](../README.md),
   [`apps/server/README.md`](../apps/server/README.md), and
   [`infra/pi-image/pi-gen/README.md`](../infra/pi-image/pi-gen/README.md).

This matrix defines the policy view. `tools/dev/check_hygiene.py` reads it as
the runtime-policy coverage contract and compares the referenced anchors
against version files, package metadata, Docker/CI config, and Pi
install/image helpers. The version files, package metadata, Dockerfile tags,
and shared GitHub Actions setup actions remain the machine-readable anchors for
the concrete values.

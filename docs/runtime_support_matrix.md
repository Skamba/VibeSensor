# Runtime Support Matrix

This file is the canonical human-readable Python and Node support-policy reference
for VibeSensor. Other setup and workflow docs should point here instead of
restating version policy inline.

## Current support matrix

| Environment / path | Supported Python policy | Supported Node policy | Current source-of-truth files and notes |
|---|---|---|---|
| Native development, local tooling, and simulator runs | Use the exact version from [`.python-version`](../.python-version) (`3.14.3` today). | Use the major version from [`.nvmrc`](../.nvmrc) (`22.x` today). | `make doctor` and `tools/dev/check_prerequisites.py` enforce these local expectations. This is the recommended path for backend work, local UI work, and local CI reproduction. |
| GitHub Actions CI and release builders | Use the same value from [`.python-version`](../.python-version). | Use the same value from [`.nvmrc`](../.nvmrc). | The shared CI setup paths and workflows should resolve versions from the version files rather than restating them inline. |
| Docker / container build path | The runtime image tag must match [`.python-version`](../.python-version). | The UI build-stage tag must match [`.nvmrc`](../.nvmrc). | [`apps/server/Dockerfile`](../apps/server/Dockerfile) is the concrete build path, and `tools/dev/check_hygiene.py` rejects drift from the version files. |
| Installable backend package / wheel compatibility | The backend package declares a minimum of `>=3.13` in [`apps/server/pyproject.toml`](../apps/server/pyproject.toml). | Not applicable. | This is the compatibility floor for the packaged server, not the exact native-dev or CI pin. Backend lint/type settings should target this same floor rather than the exact native toolchain pin. |
| Manual Raspberry Pi install and on-device runtime | Support follows the Raspberry Pi OS Lite (Trixie) baseline and requires the installed `python3` to satisfy the packaged-server floor from [`apps/server/pyproject.toml`](../apps/server/pyproject.toml) (`>=3.13` today). | Not required on-device. | [`apps/server/scripts/install_pi.sh`](../apps/server/scripts/install_pi.sh) validates `python3` before creating the venv. The Pi runtime path stays OS-baseline-driven rather than tied to the exact native-dev pin in `.python-version`. |
| Prebuilt Pi image build | Builders use [`.python-version`](../.python-version) while producing the app artifacts, and the resulting image targets Raspberry Pi OS Lite (Trixie, armhf). | Builders use [`.nvmrc`](../.nvmrc) for the UI build; Node is not required on-device after the image is built. | See [`infra/pi-image/pi-gen/README.md`](../infra/pi-image/pi-gen/README.md) plus the weekly/manual Pi-image workflows for the supported image-build path. |

## Ownership for future updates

When the supported Python or Node policy changes, update this matrix in the same
change set as the machine-readable source files it references.

1. If the native-dev / CI / Docker Python pin changes, update
   [`.python-version`](../.python-version) first, then update dependent
   Docker tags, setup actions/workflows, and docs that point at the native pin.
2. If the native-dev / CI / Docker Node policy changes, update
   [`.nvmrc`](../.nvmrc) first, then update dependent Docker tags,
   setup-node usage, and docs that point at the Node policy.
3. If backend package compatibility changes independently from the native pin,
   update [`apps/server/pyproject.toml`](../apps/server/pyproject.toml), the
   backend lint/type settings that intentionally target that floor, and any docs
   that describe the packaged-server compatibility floor.
4. If the supported Raspberry Pi OS or on-device runtime baseline changes,
   update this matrix plus the matching deployment/image docs in
   [`README.md`](../README.md),
   [`apps/server/README.md`](../apps/server/README.md), and
   [`infra/pi-image/pi-gen/README.md`](../infra/pi-image/pi-gen/README.md).

This matrix defines the policy view. The version files, package metadata,
Dockerfile tags, and workflow setup steps remain the machine-readable anchors
that later alignment and drift-check issues should keep in sync.

This file is the canonical AI guidance entrypoint and short index. Preserve guardrails when shortening; move area rules to narrower files, do not drop them.

## Guidance stack
- Start here for repo invariants and validation routing.
- Shared workflow, docs, PR, CI, and safety rules live in `.github/instructions/general.instructions.md`.
- Backend rules: `.github/instructions/backend.instructions.md`; updater rules: `.github/instructions/backend-updates.instructions.md`.
- Frontend rules: `.github/instructions/frontend.instructions.md`; firmware rules: `.github/instructions/firmware.instructions.md`.
- Pi image rules: `.github/instructions/pi-image.instructions.md`; backend test rules: `.github/instructions/tests.instructions.md`.
- Use `docs/ai/repo-map.md` only when `rg`, file names, imports, and tests do not reveal ownership.
- Do not add more files under `docs/ai/`. Design docs under `docs/designs/` must declare `Status: Active`, `Historical`, or `Superseded`; only Active docs are current guidance.

## Repo invariants
- VibeSensor contains a Python backend (`apps/server/`), TypeScript/Vite UI (`apps/ui/`), ESP32 firmware (`firmware/esp/`), and Raspberry Pi image build (`infra/pi-image/`).
- Raw ingest/sample acceleration may use g; post-stop analysis outputs expose vibration strength/intensity in dB. Only the persisted `diagnosis` block reports amplitude at the diagnosed order in mg, always next to its dB above floor (`docs/metrics.md`).
- Users see confidence only as one of three action-defined levels (Strong / Moderate / Weak); never expose a confidence percentage in the UI or the PDF.
- Canonical dB math: `apps/server/vibesensor/dsp/vibration_strength.py::vibration_strength_db_scalar()`.
- Static config that does not change between deployments belongs in Python constants, not runtime file loaders.
- Internal shared logic stays in the server package. Generated UI constants come from backend sources (`vibesensor.domain`, `vibesensor.dsp`).
- Backend code lives in per-feature packages under `apps/server/vibesensor/`; `common/` holds only small cross-cutting helpers (JSON, time, logging, errors, units, process env settings). Runtime bootstrap/subprocess orchestration belongs in `app/` or the owning feature package.
- Pi hotspot provisioning is offline-first; required packages are baked into the image. Pi image outputs must be deterministic and self-validated.

## Backend/domain boundaries
- Domain objects own classification, ranking, lifecycle, and computation. Code at persistence, transport, PDF, and HTTP edges translates; it does not duplicate domain logic.
- Import every name from the module that defines it; package `__init__.py` files stay empty or docstring-only (no re-export facades).
- Annotate collaborators with their concrete class (use `if TYPE_CHECKING:` imports to avoid runtime cycles). Add a `Protocol` only for two or more real implementations or a seam the real class cannot serve cheaply in tests (hardware, subprocess, network).
- Wire services with plain constructor calls in `apps/server/vibesensor/app/composition.py`; do not add `*Deps`/`*Bundle` wiring layers.
- Summary/run/settings codecs live with the feature that owns the data (`summary/`, `recording/`, `settings/`); do not rebuild payload-driven business logic in report/history/web consumers.
- Package dependencies are enforced by the three import-linter contracts in `apps/server/pyproject.toml`: entrypoints sit on top (`cli`/`simulator` > `app` > `web` > feature packages > `domain`/`common`); the live path (`ingest`, `live`, `dsp`) never imports `analysis`, `history`, `recording`, `report`, or `summary`; `report` never imports `analysis`. Annotation-only imports are exempt.

## Validation router
- Cleanup: `make clean` removes fast regenerated build/test outputs; `make pristine` removes ignored generated/cache/runtime outputs and then requires `make setup` for native dev.
- Run `make ci` before pushing (lint, type checks, backend tests, UI unit tests). Use ACT only when GitHub workflow or Docker parity is needed.
- Docs or instruction-only changes need no local gate.
- Backend source: `make lint`, `make typecheck-backend`, and targeted `pytest -q apps/server/tests/<module>/`; broad synthetic matrices use `make test-diagnostic-matrix`.
- Backend API/contracts/shared UI constants: add `make sync-contracts` and `make ui-typecheck`.
- Frontend logic/contracts/composition: `make ui-typecheck`; add `cd apps/ui && npm run build`, `npm run test:unit`, or `npm run test:smoke` when the changed seam requires it.
- Firmware: `cd firmware/esp && pio run`; for protocol/native parity add `python tools/firmware/generate_protocol_contract_fixtures.py --check` and `cd firmware/esp && pio test -e native`.
- Pi image: use the narrow path, `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh` or `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh`; use `./infra/pi-image/pi-gen/validate-image.sh [artifact]` to validate an existing artifact.
- Do not use ACT for `.github/workflows/weekly-pi-image.yml`; it requires GitHub's `ubuntu-24.04-arm` runner label, which is intentionally not mapped in `.actrc`.
- Full command details, ACT limits, test placement, and CI job notes live in `docs/testing.md`.

## PR/CI flow
- Branch from latest `main`, open a PR to `main`, and watch checks with `gh pr checks <PR_NUMBER> --watch`; merge with `gh pr merge --squash` once green unless the user explicitly wants watch-only.
- Inspect failing annotations, failing test names, and concise log tails; do not paste full CI logs into context.
- Fix failures caused by the branch, push, and re-watch until required CI is green and the PR is merged. Do not merge on red required checks; document unrelated/flaky blockers.
- Prefer squash merge unless repo convention or user instruction says otherwise.

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
- Raw ingest/sample acceleration may use g; post-stop analysis outputs must expose vibration strength/intensity in dB only.
- Canonical dB math: `apps/server/vibesensor/vibration_strength.py::vibration_strength_db_scalar()`.
- Static config that does not change between deployments belongs in Python constants, not runtime file loaders.
- Internal shared logic stays in the server package. Generated UI constants come from backend sources under `vibesensor.shared.*`.
- `vibesensor.shared` is for stable contracts, ports, codecs, constants, and pure helpers. Runtime bootstrap/subprocess orchestration belongs in `apps/server/vibesensor/app/` or the owning `use_cases/**` module.
- Pi hotspot provisioning is offline-first; required packages are baked into the image. Pi image outputs must be deterministic and self-validated.

## Backend/domain boundaries
- Domain objects own classification, ranking, lifecycle, and computation. Boundary adapters translate; they do not duplicate domain logic.
- Import domain objects from `vibesensor.domain`, not individual domain module files.
- Boundary decoders/serializers live under `apps/server/vibesensor/shared/boundaries/`; do not rebuild payload-driven business logic in report/history/runtime consumers.
- Factories for already-typed internal metadata, snapshots, or computed state belong on domain objects or the owning use case, not boundary decoders.
- Backend layer DAG, enforced by `apps/server/pyproject.toml` and `tools/dev/verify_backend_static_guards.py`: `domain` imports no project layers; `shared` may import `domain`; `use_cases` may import `domain, shared`; `infra` may import `domain, shared`; `adapters` may import `domain, shared, infra, use_cases`; `app` may import all. `shared -> domain` and `infra -> domain` are allowed; inward leakage such as `use_cases -> adapters` is not.

## Validation router
- Cleanup: `make clean` removes fast regenerated build/test/generated outputs; `make pristine` removes ignored generated/cache/runtime outputs and then requires `make setup` for native dev.
- Start with `make plan-validation`; run planned non-Docker jobs with `./.venv/bin/python tools/tests/plan_validation.py --run`, or use `--act` / `./tools/tests/run_ci_with_act.sh` only when GitHub workflow or Docker parity is needed.
- Use `./tools/tests/run_ci_with_act.sh --full-stack` only when you must force all gated CI jobs.
- Docs or instruction-only changes: run `make docs-lint` plus `make plan-validation`.
- Backend source: `make lint`, `make typecheck-backend`, and targeted `pytest -q apps/server/tests/<module>/`; broad synthetic matrices are opt-in via `make test-diagnostic-matrix`.
- Backend API/contracts/shared UI constants: add `make sync-contracts` and `make ui-typecheck`.
- Frontend logic/contracts/composition: `make ui-typecheck`; add `cd apps/ui && npm run build`, `npm run test:unit`, or `npm run test:visual` when the changed seam requires it.
- Firmware: `cd firmware/esp && pio run`; for protocol/native parity add `python tools/firmware/generate_protocol_contract_fixtures.py --check` and `cd firmware/esp && pio test -e native`.
- Pi image: use the narrow path, `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh` or `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh`; use `./infra/pi-image/pi-gen/validate-image.sh [artifact]` to validate an existing artifact.
- Do not use ACT for `.github/workflows/manual-pi-image-arm.yml` or `.github/workflows/weekly-pi-image.yml`; they require GitHub's `ubuntu-24.04-arm` runner label, which is intentionally not mapped in `.actrc`.
- Full command details, ACT limits, test placement, and CI job notes live in `docs/testing.md`.

## PR/CI flow
- Branch from latest `main`, open a PR to `main`, and use `./.venv/bin/python tools/watch_pr_checks.py --pr <PR_NUMBER> --repo Skamba/VibeSensor --merge-on-green` unless the user explicitly wants watch-only.
- Inspect failing annotations, failing test names, and concise log tails; do not paste full CI logs into context.
- Fix failures caused by the branch, push, and rerun the watcher until required CI is green and the PR is merged. Do not merge on red required checks; document unrelated/flaky blockers.
- Prefer squash merge unless repo convention or user instruction says otherwise.

---
applyTo: "apps/server/vibesensor/use_cases/updates/**,apps/server/tests/use_cases/updates/**"
---
Updater rules for the wheel-based app, firmware, Wi-Fi, release, install/rollback, and status update paths.

- `apps/server/vibesensor/use_cases/updates/manager.py` is the public updater API (start/cancel/task supervision); `job.py` holds the linear update flow and startup recovery, and `runtime.py` wires them. Keep the flow in `job.py` readable top to bottom instead of adding coordinator/planner layers. Update callers directly when methods move; do not add static passthroughs, module aliases, shims, or compatibility layers.
- Keep release JSON boundaries typed. Prefer `read_typed_json_response` and `GitHubApiClient.get_typed_json` over loose `json.loads(...)` plus manual `.get(...)` coercion. Minimal-dependency CLI validation paths may use stdlib `json` when they intentionally run without optional runtime dependencies.
- In `apps/server/vibesensor/use_cases/updates/releases/release_validation.py`, `validate-wheel-metadata` and `validate-firmware-manifest` must remain importable without optional deps such as `msgspec` or `pydantic`; keep heavier imports lazy inside `smoke-server`.
- Preserve update integrity checks and safe network/device defaults. Do not weaken validation, release decoding, firmware/app update sequencing, or rollback paths.
- Validation: run targeted `pytest -q apps/server/tests/use_cases/updates/` plus backend lint/typecheck gates when update code changes.

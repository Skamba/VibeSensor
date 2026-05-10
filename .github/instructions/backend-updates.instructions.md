---
applyTo: "apps/server/vibesensor/use_cases/updates/**,apps/server/tests/use_cases/updates/**"
---
Updater rules for the wheel-based app, firmware, Wi-Fi, release, install/rollback, and status update paths.

- `apps/server/vibesensor/use_cases/updates/manager.py` is the public facade for workflow orchestration and validation. Update callers directly when methods move; do not add static passthroughs, module aliases, shims, or compatibility layers.
- Keep release JSON boundaries typed. Prefer `read_typed_json_response` and `GitHubApiClient.get_typed_json` over loose `json.loads(...)` plus manual `.get(...)` coercion. Minimal-dependency CLI validation paths may use stdlib `json` when they intentionally run without optional runtime dependencies.
- `apps/server/vibesensor/use_cases/updates/releases/release_validation.py` may import `tenacity` lazily for `smoke-server` readiness only. `validate-wheel-metadata` and `validate-firmware-manifest` must remain importable without optional deps such as `tenacity`, `msgspec`, or `pydantic`.
- Preserve update integrity checks and safe network/device defaults. Do not weaken validation, release decoding, firmware/app update sequencing, or rollback paths.
- Validation: start with `make plan-validation`; run targeted `pytest -q apps/server/tests/use_cases/updates/` plus backend lint/typecheck gates when update code changes.

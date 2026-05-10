---
applyTo: "apps/server/**"
---
Backend rules. Use `docs/ai/repo-map.md` only for ownership lookup and `docs/domain-model.md` for the full domain graph.

- Preserve the backend layer DAG from `.github/copilot-instructions.md`. Domain/shared/use_cases/infra/adapters/app boundaries are enforced by `apps/server/pyproject.toml` and `tools/dev/verify_backend_static_guards.py`.
- Domain behavior belongs in domain objects or the owning use case. Adapters translate at persistence, transport, PDF, simulator, and HTTP boundaries; they do not duplicate classification, ranking, lifecycle, or computation.
- Route-facing modules should depend on shared ports or adapter-local protocols, not direct `infra` imports. Keep sensor metadata writes behind the client location-assignment handoff in `apps/server/vibesensor/adapters/http/clients.py`.
- Analysis adapters delegate classification/ranking to domain `Finding`.
- Keep pure math, DSP, FFT, and signal transforms functional; do not wrap them in classes without a domain reason.
- Do not create phantom domain/infrastructure types consumed by no production path, or single-consumer domain satellites that should live with their host.
- Preserve report ranking and persistence-aware diagnostics. Do not regress report ranking to max-only peak selection.
- Keep transient/impact events visible in reports without promoting them above likely persistent faults by default.
- Validate report-facing output: rendered/API/PDF text and ordering, not only helper internals. User-facing report text changes require `apps/server/vibesensor/data/report_i18n.json`.
- Prefer shared `orjson` helpers (`json_text_dumps`, `safe_json_dumps`) for backend-owned persistence/history/export JSON text. CLI/debug/log sinks may use stdlib `json` for formatting, ASCII escaping, or script portability.
- Prefer explicit payload contracts (`TypedDict`, dataclass, protocol, `JsonValue`/`JsonObject`) over `Any`. Use `object` for untrusted inputs, `ParamSpec` for callable wrappers, and focused contracts for nested state.
- For live processing/WebSocket payloads, reuse `apps/server/vibesensor/shared/types/payload_types.py` and `vibesensor.vibration_strength` instead of ad-hoc `dict[str, Any]` bags.
- Backend validation: start with `make plan-validation`; for backend source run `make lint`, `make typecheck-backend`, and targeted `pytest -q apps/server/tests/<module>/`. Add `make sync-contracts` and `make ui-typecheck` when API payloads, generated contracts, or shared backend/frontend constants change.

---
applyTo: "apps/server/**"
---
Backend rules. Use `docs/ai/repo-map.md` only for ownership lookup and `docs/domain-model.md` for the full domain graph.

- Put code in the feature package that owns it (`ingest`, `live`, `dsp`, `recording`, `analysis`, `summary`, `report`, `history`, `settings`, `speed`, `updates`, `hotspot`, `clock`, `power`, `simulator`, `web`, `app`; `domain` for core value objects, `common` for small cross-cutting helpers). Keep the package rules from `.github/copilot-instructions.md`; the import-linter contracts in `apps/server/pyproject.toml` enforce them.
- Domain behavior belongs in domain objects or the owning feature module. Persistence, transport, PDF, simulator, and HTTP code translates; it does not duplicate classification, ranking, lifecycle, or computation.
- Routes live in `web/` (one `create_*_routes` factory per group, assembled in `web/router.py` from `WebServices`); services are constructed once in `app/composition.py`.
- Keep sensor metadata writes behind the client location-assignment handoff in `apps/server/vibesensor/web/clients.py`.
- Analysis code delegates classification/ranking to domain `Finding`.
- Keep pure math, DSP, FFT, and signal transforms functional; do not wrap them in classes without a domain reason.
- Do not create phantom domain/infrastructure types consumed by no production path, or single-consumer domain satellites that should live with their host.
- Preserve report ranking and persistence-aware diagnostics. Do not regress report ranking to max-only peak selection.
- Keep transient/impact events visible in reports without promoting them above likely persistent faults by default.
- Car settings, readiness, diagnosis source checks, and report wording: check the principles in `docs/user_journeys.md` (no silent reference defaults; claim only what was tested) and update `docs/user_journey_gaps.md` when you close a gap.
- Validate report-facing output: rendered/API/PDF text and ordering, not only helper internals. User-facing report text changes require `apps/server/vibesensor/data/report_i18n.json`.
- Prefer the shared `msgspec`-backed helpers (`json_text_dumps`, `safe_json_dumps`) for backend-owned persistence/history/export JSON text. CLI/debug/log sinks may use stdlib `json` for formatting, ASCII escaping, or script portability.
- Prefer explicit payload contracts (`TypedDict`, dataclass, protocol, `JsonValue`/`JsonObject`) over `Any`. Use `object` for untrusted inputs, `ParamSpec` for callable wrappers, and focused contracts for nested state.
- For live processing/WebSocket payloads, reuse `apps/server/vibesensor/live/payload_types.py` and `vibesensor.dsp.vibration_strength` instead of ad-hoc `dict[str, Any]` bags.
- Keep the server start path light: the Pi imports everything `vibesensor.app.bootstrap` and `create_app()` import before it answers (about 5 s on a Pi 3 A+). Import slow libraries that only some requests or the first sensor data need (scipy.signal, pyfftw/scipy.fft, httpx, reportlab, the car library) on first use; `tests/app/test_import_purity.py` lists them.
- Backend validation: for backend source run `make lint`, `make typecheck-backend`, and targeted `pytest -q apps/server/tests/<module>/`. Add `make sync-contracts` and `make ui-typecheck` when API payloads, generated contracts, or shared backend/frontend constants change.

# Repo map

## Primary entry points

- Backend app: `apps/server/vibesensor/app/bootstrap.py`
- Backend service wiring: `apps/server/vibesensor/app/container.py`
- Backend route assembly: `apps/server/vibesensor/adapters/http/routes/__init__.py`
- UI app entry: `apps/ui/src/main.ts`
- UI runtime/composition root: `apps/ui/src/app/ui_app_runtime.ts`
- UI runtime owners: `apps/ui/src/app/runtime/`
- Simulator CLI: `apps/server/vibesensor/adapters/simulator/sim_sender.py`
- Firmware app: `firmware/esp/src/main.cpp`
- Pi image build: `infra/pi-image/pi-gen/build.sh`
- Local stack entry point: `docker-compose.yml`

## Top-level layout

- `apps/server/`: backend package, configs, tests, scripts, systemd units, public UI assets, simulator, and config tooling.
- `apps/ui/`: TypeScript/Vite dashboard and Playwright tests.
- `firmware/esp/`: ESP32 firmware.
- `vibesensor/vibration_strength.py`, `vibesensor/strength_bands.py`: shared vibration math and unit logic (inlined from former `libs/core/`).
- `infra/pi-image/pi-gen/`: Raspberry Pi image build pipeline.
- `docs/`: human-facing docs plus AI repo maps and runbooks.

## Backend package layout

- `app/`: `bootstrap.py` creates the FastAPI app, `container.py` wires the flat `RuntimeState`, and `settings.py` owns config loading/defaults.
- `adapters/http/`: route groups, Pydantic HTTP models, and schema/contract export.
- `adapters/websocket/`: WebSocket hub plus schema export.
- `adapters/persistence/`: SQLite history DB, runlog I/O, and boundary decoders/serializers between payload shapes and domain aggregates.
- `adapters/pdf/`: PDF renderer pages, drawing primitives, and `pdf_engine.py`.
- `adapters/udp/`, `adapters/gps/`, `adapters/simulator/`: UDP transport, GPS monitor, and simulator tooling.
- `infra/runtime/`: flat `RuntimeState`, lifecycle management, processing loop, and websocket broadcast coordination.
- `infra/processing/`, `use_cases/diagnostics/`: live signal processing vs post-stop findings/orchestration logic.
- `infra/metrics/`: recording pipeline package (`logger.py`, `post_analysis.py`, `sample_builder.py`).
- `infra/config/`, `infra/workers/`, `infra/hotspot/`: settings stores, worker pool, and hotspot self-heal infrastructure.
- `domain/`: DDD-aligned domain model package.  Each primary domain object
  lives in its own dedicated file: `car.py` (Car, TireSpec), `sensor.py` (Sensor,
  SensorPlacement), `measurement.py` (Measurement, VibrationReading),
  `run.py` (Run lifecycle), `test_run.py` (TestRun aggregate),
  `diagnostic_case.py` (DiagnosticCase aggregate), `diagnosis.py` (Diagnosis),
  `diagnostic_reasoning.py` (DiagnosticReasoning),
  `run_capture.py` (RunCapture), `run_setup.py` (RunSetup),
  `configuration_snapshot.py`, `symptom.py`, `test_plan.py`,
  `recommended_action.py`, `driving_segment.py`, `observation.py`,
  `signature.py`, `hypothesis.py`, `vibration_origin.py`,
  `speed_source.py` (SpeedSource), `driving_phase.py` (DrivingPhase),
  `finding.py` (FindingKind, VibrationSource, Finding),
  `finding_evidence.py` (FindingEvidence),
  `confidence_assessment.py` (ConfidenceAssessment),
  `location_hotspot.py` (LocationHotspot),
  `speed_profile.py` (SpeedProfile),
  `run_suitability.py` (RunSuitability, SuitabilityCheck),
  `report.py` (Report), `run_status.py` (RunStatus, RUN_TRANSITIONS).
  `domain/services/` owns
  observation extraction, signature recognition, hypothesis evaluation,
  and test planning. Domain objects own
  classification, ranking, actionability, surfacing, lifecycle, and
  query logic; pipeline adapters in `analysis/` delegate to them. See
  `docs/domain-model.md` for the full relationship map and modeling rules.
- `adapters/persistence/boundaries/`: explicit ingress/egress decoders and serializers between
  domain aggregates (`DiagnosticCase`, `TestRun`) and
  summary/persistence/report payload shapes; `diagnostic_case.py::test_run_from_summary()`
  reconstructs domain aggregates, and individual boundary serializers
  (`finding_payload_from_domain`, `origin_payload_from_finding`, etc.) handle
  re-serialization at history/export/report call sites.
- `adapters/persistence/history_db/`: SQLite-backed history and settings persistence (3 files: `__init__.py` with `HistoryDB`, `_schema.py`, `_samples.py`). `RunStatus` and state-transition logic live in `domain/run/status.py`.
- `use_cases/history/`: focused history service layer (run query/delete,
  reports, exports, helpers) above `adapters/persistence/history_db/`; run/report services project
  persisted analyses through reconstructed domain aggregates before returning
  API payloads, building PDFs, or emitting exports.
- `use_cases/reporting/`: report-template builders, pattern-to-parts mapping, i18n helpers, and analysis-summary-to-domain-Report factory (`mapping.py::build_report_from_summary()`).
- `use_cases/updates/` + `domain/updates/`: update workflow orchestration plus update state/value objects; workflow validation and rollback snapshot creation must both succeed before a live install begins.
- `apps/ui/src/app/runtime/`: explicit UI runtime owners for shell/chrome state, live transport/payload application, and spectrum/chart orchestration beneath the `UiAppRuntime` composition root.

## Test layout

- `apps/server/tests/` uses a mirrored `unit/`, `integration/`, and `architecture/` layout.
- Cross-cutting coverage lives in `integration/` and `architecture/`.
- Regression tests live in the feature directory they primarily test, or in `integration/` for cross-cutting regressions.
- Shared test support lives at the test root (`conftest.py`, `_paths.py`, focused helper modules, and the `test_support/` package including `findings.py` for canonical finding-payload factories).
- Full map: `docs/testing.md`.

## Source-of-truth rule

When code movement changes this map, update `docs/ai/repo-map.md`, `.github/copilot-instructions.md`, and the affected README or instruction file in the same change set.

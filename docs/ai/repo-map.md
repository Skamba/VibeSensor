# Repo map

## Primary entry points

- Backend app: `apps/server/vibesensor/app/bootstrap.py`
- Backend service wiring: `apps/server/vibesensor/app/container.py`
- Backend route assembly: `apps/server/vibesensor/adapters/http/__init__.py`
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

- `app/`: startup and wiring. `bootstrap.py` creates the FastAPI app, `container.py` builds the flat `RuntimeState`, and `settings.py` owns YAML config loading and validation.
- `adapters/http/`: health, clients, settings, recording, history, websocket, updates, car library, and debug route groups; `adapters/http/__init__.py` assembles the router.
- `adapters/websocket/hub.py`: live WebSocket connection fan-out and payload delivery.
- `adapters/persistence/`: SQLite history DB (`history_db/`), JSONL runlog I/O (`runlog.py`), and the static car library loader (`car_library.py`).
- `adapters/pdf/`: PDF/report rendering pipeline and report mapping entrypoints.
- `adapters/udp/`, `adapters/gps/`, `adapters/simulator/`, `adapters/hotspot/`: UDP protocol transport, GPS speed ingestion, simulator tooling, and hotspot/AP operational adapters.
- `infra/runtime/`: flat `RuntimeState`, lifecycle management, processing loop, health snapshots, and WebSocket broadcast coordination.
- `infra/processing/`: signal processing pipeline (buffers, FFT, payload shaping, and processor facade).
- `infra/config/`: runtime analysis/settings stores used by runtime wiring and recording flows.
- `infra/workers/`: worker-pool infrastructure.
- `use_cases/diagnostics/`: post-stop diagnostics pipeline. `findings.py` and `top_cause_selection.py` delegate classification and ranking to the domain `Finding`; `location_analysis.py` owns the location-analysis pipeline; `analysis_window.py` owns the `AnalysisWindow` dataclass; `_types.py` owns `PhaseEvidence`, `FindingPayload`, and `AnalysisSummary`.
- `use_cases/history/`: run query/delete, PDF report generation, CSV/ZIP exports, and history-facing helper orchestration above persistence.
- `use_cases/run/`: recording pipeline orchestration; `logger.py` owns `RunRecorder`, `post_analysis.py` owns the background analysis queue, and `sample_builder.py` owns pure sample-building helpers.
- `use_cases/updates/`: wheel-based updater workflow orchestration, firmware cache, ESP flashing, release discovery, install, rollback, runner, Wi-Fi, and status tracking.
- `shared/`: cross-cutting typed payloads (`shared/types/`), boundary serializers/decoders (`shared/boundaries/`), exceptions (`shared/errors/`), JSON helpers (`shared/utils/`), location identifiers (`shared/ids/`), and run-context helpers.
- `domain/`: DDD-aligned domain model package. Each primary domain object
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
  query logic; diagnostics use cases delegate to them. See
  `docs/domain-model.md` for the full relationship map and modeling rules.
- `apps/ui/src/app/runtime/`: explicit UI runtime owners for shell/chrome state, live transport/payload application, and spectrum/chart orchestration beneath the `UiAppRuntime` composition root.

## Test layout

- `apps/server/tests/` mirrors the backend package layout with `app/`, `shared/`, `domain/`, `use_cases/`, `adapters/`, and `infra/` subtrees.
- Cross-cutting coverage lives in `integration/` and `hygiene/`.
- Regression tests live in the feature directory they primarily test, or in `integration/` for cross-cutting regressions.
- Shared test support lives at the test root (`conftest.py`, `_paths.py`, focused helper modules, and the `test_support/` package including `findings.py` for canonical finding-payload factories).
- Full map: `docs/testing.md`.

## Source-of-truth rule

When code movement changes this map, update `docs/ai/repo-map.md`, `.github/copilot-instructions.md`, and the affected README or instruction file in the same change set.

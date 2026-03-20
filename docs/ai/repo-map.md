# Repo map

Scope: single source of truth for detailed file layout, entry points, package structure, and module ownership. Behavioral rules live in `.github/copilot-instructions.md` and `.github/instructions/*.instructions.md`.

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
- `cli/`: CLI entry points — `server.py` (main server), `report.py` (report generation), `preflight.py` (config preflight), `hotspot_config.py` (hotspot config export for shell scripts), `http_api_schema_export.py`, `ws_schema_export.py`.
- `vibesensor/vibration_strength.py`, `vibesensor/strength_bands.py`: shared vibration math and unit logic. Hot-path functions accept numpy arrays; scalar functions remain pure Python.
- `infra/pi-image/pi-gen/`: Raspberry Pi image build pipeline.
- `docs/`: human-facing docs plus AI repo maps and runbooks.

## Backend package layout

- `app/`: startup and wiring. `bootstrap.py` creates the FastAPI app, `container.py` builds a lifecycle-focused `RuntimeState` plus the top-level `AppRuntime` bundle, `runtime_state.py` owns those app-facing runtime bundles and types eligible read-side runtime fields to `shared/ports.py`, and `settings.py` owns YAML config loading and validation.
- `adapters/http/`: health, clients, settings, recording, history, websocket, updates, car library, and debug route groups; `adapters/http/dependencies.py` owns the grouped router dependency dataclasses and `adapters/http/__init__.py` assembles the router from them.
- `adapters/websocket/hub.py`: live WebSocket connection fan-out and payload delivery.
- `adapters/persistence/`: SQLite history DB (`history_db/` keeps `HistoryDB` as the public facade and splits internals across `_run_lifecycle.py`, `_sample_io.py`, `_queries.py`, `_schema.py`, and `_samples.py`) and the static car library loader (`car_library.py`).
- `adapters/pdf/`: PDF/report rendering pipeline and report mapping entrypoints.
- `adapters/udp/`, `adapters/gps/`, `adapters/simulator/`, `adapters/hotspot/`: UDP protocol transport, GPS speed ingestion, simulator tooling, and hotspot/AP operational adapters.
- `infra/runtime/`: lifecycle management, processing loop, runtime health state, and WebSocket broadcast coordination. `registry.py` owns raw `ClientRegistry` state tracking plus `client_snapshots()`, while `client_snapshot.py` owns the client-row presenter reused by `/api/clients` and `ws_broadcast.py`.
- `infra/processing/`: signal processing pipeline (buffers, FFT, payload shaping, and processor facade).
- `infra/config/`: runtime settings store (single `SettingsStore` owns both analysis and device settings) used by runtime wiring and exposed to use-cases through focused shared read ports.
- `infra/workers/`: worker-pool infrastructure.
- `use_cases/diagnostics/`: post-stop diagnostics pipeline. See `docs/analysis_pipeline.md` for the full data flow, pipeline steps, and module map. `run_data_preparation.py` owns `PreparedRunData` plus run timing/speed/phase/sensor preparation, `findings.py` owns reference-check and peak/order orchestration, `peak_binning.py` owns persistent-peak accumulation/scoring, `peak_table.py` owns internal peak-table row ranking/statistics, `signal_aggregation.py` owns speed/location summary aggregation, `math_utils.py` owns generic statistics/correlation helpers, `speed_profile_helpers.py` owns speed-profile assembly helpers, `order_analysis.py` now owns the core order-matching/scoring/assembly primitives, `order_pipeline.py` owns `OrderAnalysisSession` plus the `_build_order_findings()`/multi-location orchestration layer above those primitives, and `order_heuristics.py` owns the pure diffuse-excitation, localization-override, and engine-alias heuristics; `top_cause_selection.py` delegates classification and ranking to the domain `Finding`; `location_analysis.py` owns the location-analysis pipeline and `LocationAnalysisResult` typed return; `plots.py` now keeps plot-series/FFT/spectrogram orchestration over diagnostics-local value objects, `summary_builder.py` focuses on `RunAnalysis` orchestration and domain/app summary assembly inputs, and `_types.py` owns diagnostics-local helper/value types such as `AccelStatistics`, speed-breakdown rows, and plot/spectrogram value objects. Boundary summary payloads live in `shared/boundaries/analysis_payload.py`, while `shared/boundaries/summary_serialization.py` owns the dedicated domain/app → payload seam and history-use-case callers now receive persisted-summary projection through injected adapter wiring instead of importing that boundary projector directly. The package `__init__.py` re-exports only high-level analysis entrypoints; PDF rendering types/helpers now live under `adapters/pdf/`.
- `use_cases/history/`: run query/delete, PDF report generation, CSV/ZIP exports, and history-facing helper orchestration above persistence ports. `helpers.py` owns the local `HistoryRecord` TypedDict plus generic history workflow helpers, while `report_interpretation.py` owns pure report-domain interpretation consumed by the PDF mapper.
- `use_cases/run/`: recording pipeline orchestration; `lifecycle_state.py` owns `RunLifecycleState` plus the active-run snapshot, `persistence_writer.py` owns history-write coordination/retry bookkeeping, `sample_flush.py` owns sample-building/flush decisions and auto-stop checks, `status_reporting.py` owns the status/health payload helpers, `logger.py` owns the thin `RunRecorder` orchestrator, `post_analysis.py` owns the background analysis queue above the injected run-persistence/analysis/error boundary, and `sample_builder.py` owns pure sample-building helpers.
- `use_cases/updates/`: wheel-based updater workflow orchestration, runtime prerequisite validation, firmware cache, ESP flashing, release discovery, install, rollback, runner, Wi-Fi, and status tracking.
- `shared/`: cross-cutting typed payloads and ports (`shared/types/` and `shared/ports.py`), boundary serializers/decoders (`shared/boundaries/`), exceptions (`shared/exceptions.py`), JSON helpers (`shared/json_utils.py`), location identifiers (`shared/locations.py`), run-context helpers, and shared pure vehicle-order math (`shared/order_bands.py`). `shared/ports.py` owns the current run-history persistence, active-client lookup, latest-sample/latest-metrics, resolved-speed, and read-only settings ports used by runtime/history/recording flows; `shared/types/` stays focused on payload/model types such as `sensor_frame.py`, `health_snapshot.py`, the feature-scoped Pydantic HTTP contract package `shared/types/api_models/`, and the typed backend/API payloads; `shared/boundaries/run_log.py` owns JSONL run-log decoding/normalization shared by diagnostics and persistence; and `shared/boundaries/diagnostic_case.py` owns summary projection, typed speed/suitability decoding, and shared metadata-to-case reconstruction (`case_context_from_metadata`).
- `domain/`: DDD-aligned domain model package. Primary domain objects
  live under `vibesensor/domain/`; closely related value objects share
  a file with their parent aggregate:
  `car.py` (Car, TireSpec, OrderReferenceSpec, CarSnapshot),
  `sensor.py` (Sensor, SensorPlacement),
  `run.py` (Run lifecycle), `test_run.py` (TestRun aggregate),
  `diagnostic_case.py` (DiagnosticCase aggregate, Symptom),
  `run_capture.py` (RunCapture, RunSetup, ConfigurationSnapshot, Measurement, VibrationReading),
  `test_plan.py` (TestPlan, RecommendedAction + planning service functions),
  `driving_segment.py` (DrivingSegment, DrivingPhase, DrivingPhaseInterval, DrivingPhaseSegment),
  `vibration_origin.py`,
  `speed_source.py` (SpeedSource),
  `finding.py` (FindingKind, VibrationSource, Finding, FindingEvidence, Signature),
  `confidence_assessment.py` (ConfidenceAssessment),
  `location_hotspot.py` (LocationHotspot, LocationIntensitySummary),
  `order_match.py` (OrderMatchObservation),
  `speed_profile.py` (SpeedProfile),
  `run_suitability.py` (RunSuitability, SuitabilityCheck),
  `run_status.py` (RunStatus, RUN_TRANSITIONS),
  `snapshots.py` (AnalysisSettingsSnapshot, RunContextSnapshot, RunMetadataSnapshot, SpeedProfileSummary, DrivingPhaseSummary),
  `strength_metrics.py` (StrengthMetrics, StrengthPeak).
  Domain objects own
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

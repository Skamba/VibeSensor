# Domain model

This document describes the vibration-diagnostics domain model: the primary
domain objects, the relationships between them, and the adapter types that
exist only at persistence/transport/rendering boundaries.

## Domain object relationship map

```
Car ──aspects──▶ Run (aggregate root: lifecycle, readings, duration)
                  ▲                    │
Sensor ──has──▶ SensorPlacement        │ produces
                  │                    ▼
SpeedSource ──configures──▶ Run   [AnalysisWindow] (analysis-layer type)
                                       │ analyzed into
Measurement ──recorded in──▶ Run       ▼
  │                              Finding (richest: classification,
  │ converts to                   ranking, actionability, scoring)
  ▼                                    │ collected by
VibrationReading (dB)                  ▼
                                 Report (assembled output)
```

### Central objects in the workflow

| Object | Role | Key owned behavior |
|--------|------|--------------------|
| **Run** | Aggregate root | Lifecycle (start/stop/stopped), status transitions, phase tracking |
| **Finding** | Richest domain object | Kind (diagnostic/reference/informational), classification, actionability, surfacing, confidence thresholds, deterministic ranking, phase-adjusted scoring (flat `cruise_fraction`), vibration-source enum (`VibrationSource`), speed-band helper functions (`speed_bin_label`, `speed_band_sort_key`), REF_ prefix cross-check warning |
| **Report** | Assembled output | Finding queries (`finding_count` property), primary-finding selection, raw temporal values (`report_date`, `duration_s`); construction from analysis summary delegated to `report/mapping.py` |

### Supporting domain objects

| Object | Role | Key owned behavior |
|--------|------|--------------------|
| **Car** | Vehicle under test | Tire-circumference computation from aspect specs (via `TireSpec`), display name (always includes type), dimension validation (rejects zero and negative values), immutable aspects (`MappingProxyType`) |
| **Sensor** | Accelerometer node | Display name, placement status queries |
| **SensorPlacement** | Mounting position | Position category classification (wheel/drivetrain/body) |
| **Measurement** | Raw sample value object | Conversion to VibrationReading (dB) |
| **VibrationReading** | Processed dB value object | Severity level lookup, dB computation |
| **SpeedSource** | Speed acquisition config | Source-kind classification (via `SpeedSourceKind` StrEnum), effective speed resolution, cross-field invariant (MANUAL requires `manual_speed_kmh > 0`) |

### Object containment and derivation

- **Sensor** contains an optional **SensorPlacement**.
- **Run** tracks lifecycle via ``start()``/``stop()`` guards and an ``is_recording`` property.  Reading accumulation is handled by the recording pipeline, not the domain object.
- **Report** contains a tuple of **Finding** instances.
- **Finding** is derived from analysis of **AnalysisWindow** data (analysis-layer type, not a domain object).
- **Car** aspects (tire dimensions) drive order-analysis hypothesis generation.
- **SpeedSource** configures how speed is obtained during a **Run**.

## Edge adapters (not domain objects)

These types exist only at boundaries and should not own domain behavior:

| Type | Location | Boundary |
|------|----------|----------|
| `CarConfig` | `backend_types.py` | Persistence/config → domain `Car` |
| `SensorConfig` | `backend_types.py` | Persistence/config → domain `Sensor` |
| `SpeedSourceConfig` | `backend_types.py` | Persistence/config → domain `SpeedSource` |
| `SensorFrame` | `protocol.py` | Binary protocol → raw sample data |
| `RunMetadata` | `backend_types.py` | Run-level configuration snapshot |
| `PhaseEvidence` | `analysis/_types.py` | Phase evidence TypedDict for pipeline serialization |
| `FindingPayload` | `analysis/_types.py` | Dict-based analysis pipeline payload |
| `AnalysisSummary` | `analysis/_types.py` | Analysis summary TypedDict |
| `SuspectedVibrationOrigin` | `analysis/_types.py` | Origin summary TypedDict (key: `suspected_source`) |
| `LocalizationAssessment` | `analysis/summary_builder.py` | Spatial interpretation of finding evidence |
| `ReportTemplateData` | `report/report_data.py` | PDF-rendering data classes |
| `ReportMappingContext` | `report/mapping.py` | Template mapping adapter |
| `build_report_from_summary()` | `report/mapping.py` | Factory: analysis summary dict → domain `Report` |
| `SummaryView` | `report/mapping.py` | Typed read accessor over `SummaryData` dict |
| `HistoryRunPayload` | `backend_types.py` | API transport TypedDict for history runs |

## File layout

Each main behavior-owning domain object lives in its own dedicated file
within `apps/server/vibesensor/domain/`:

| File | Domain objects | Rationale |
|------|---------------|-----------|
| `measurement.py` | `Measurement`, `VibrationReading` | Tightly coupled raw-sample-to-reading pipeline |
| `run.py` | `Run` | Aggregate root with in-memory lifecycle (start/stop guards, ``is_recording`` property) |
| `speed_source.py` | `SpeedSourceKind`, `SpeedSource` | SpeedSourceKind StrEnum and speed acquisition concern |
| `sensor.py` | `SensorPlacement`, `Sensor` | Tightly coupled sensor-and-position pair |
| `car.py` | `Car`, `TireSpec` | Vehicle geometry and tire computation |
| `driving_phase.py` | `DrivingPhase` | Driving-phase StrEnum (the `AnalysisWindow` class itself lives in `analysis/analysis_window.py`) |
| `finding.py` | `FindingKind`, `VibrationSource`, `Finding`, `speed_bin_label`, `speed_band_sort_key` | Richest domain object (kind, classification, ranking, scoring, dB strength, vibration-source enum, speed-band helper functions, flat `cruise_fraction` for phase adjustment) |
| `report.py` | `Report` | Assembled diagnostic output (construction from analysis summary lives in `report/mapping.py::build_report_from_summary()`) |
| `run_status.py` | `RunStatus`, `RUN_TRANSITIONS`, `transition_run` | Persisted run lifecycle state machine (enforcing) |

All domain objects are re-exported from `vibesensor.domain` (the package
`__init__.py`).  Consumers import from `vibesensor.domain`, not from
individual module files, unless they need a very specific internal symbol.

## Modeling rules

1. **Domain objects own behavior.**  Classification, ranking, actionability,
   surfacing, lifecycle, and computation logic live on the domain objects —
   not in helper modules, pipeline stages, or route handlers.

2. **Adapters bridge, they do not own.**  Config, payload, export, and
   persistence types convert to/from domain objects but do not duplicate
   domain logic.  `LocalizationAssessment` delegates
   classification and ranking to domain `Finding`.

3. **Composition over inheritance.**  Domain objects compose via containment
   (Sensor has SensorPlacement, Report has Findings) rather than class
   hierarchies.

4. **Frozen dataclasses by default.**  All domain objects are immutable
   (`@dataclass(frozen=True, slots=True)`).

5. **No framework coupling.**  Domain objects depend only on the Python
   standard library plus the shared `vibesensor.vibration_strength` and
   `vibesensor.strength_bands` modules.

6. **Stateless transforms stay functional.**  Pure math, DSP, FFT, and
   signal-processing functions remain as plain functions in `processing/`
   and `analysis/` — they are not wrapped in classes unless there is a
   strong domain reason.

7. **Naming convention.**  Use simple domain names (`Car`, `Sensor`, `Run`,
   `Finding`) in domain logic.  Use narrower names (`CarConfig`,
   `FindingPayload`, `ReportTemplateData`) only at boundaries.

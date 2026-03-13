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
SpeedSource ──configures──▶ Run   AnalysisWindow (phase-aligned chunk)
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
| **Run** | Aggregate root | Lifecycle (start/stop), status transitions |
| **Finding** | Richest domain object | Kind (diagnostic/reference/informational), classification, actionability, surfacing, confidence quantisation, deterministic ranking, phase-adjusted scoring |
| **Report** | Assembled output | Finding queries, primary-finding selection |

### Supporting domain objects

| Object | Role | Key owned behavior |
|--------|------|--------------------|
| **Car** | Vehicle under test | Tire-circumference computation from aspect specs |
| **Sensor** | Accelerometer node | Display name, placement status queries |
| **SensorPlacement** | Mounting position | Position category classification (wheel/drivetrain/body) |
| **Measurement** | Raw sample value object | Conversion to VibrationReading (dB) |
| **VibrationReading** | Processed dB value object | Severity level lookup, dB computation |
| **SpeedSource** | Speed acquisition config | Source-kind classification, effective speed resolution |
| **AnalysisWindow** | Analysis chunk | Phase classification, speed containment, analyzability |

### Object containment and derivation

- **Sensor** contains an optional **SensorPlacement**.
- **Run** tracks lifecycle status (via **RunStatus**).  Reading accumulation is handled by the recording pipeline, not the domain object.
- **Report** contains a tuple of **Finding** instances.
- **Finding** is derived from analysis of **AnalysisWindow** data.
- **AnalysisWindow** is derived from phase segmentation of a **Run**.
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
| `FindingPayload` | `analysis/_types.py` | Dict-based analysis pipeline payload |
| `OrderAssessment` | `analysis/top_cause_selection.py` | Report-level adapter wrapping domain `Finding`, adds aggregation fields |
| `LocalizationAssessment` | `analysis/summary_builder.py` | Spatial interpretation of finding evidence |
| `ReportTemplateData` | `report/report_data.py` | PDF-rendering data classes |
| `ReportMappingContext` | `report/mapping.py` | Template mapping adapter |
| `SummaryView` | `report/mapping.py` | Typed read accessor over `SummaryData` dict |
| `HistoryRunPayload` | `backend_types.py` | API transport TypedDict for history runs |

## File layout

Each main behavior-owning domain object lives in its own dedicated file
within `apps/server/vibesensor/domain/`:

| File | Domain objects | Rationale |
|------|---------------|-----------|
| `measurement.py` | `AccelerationSample` (`Measurement`), `VibrationReading` | Tightly coupled raw-sample-to-reading pipeline |
| `session.py` | `SessionStatus`, `Run` | Aggregate root with in-memory lifecycle (PENDING → RUNNING) |
| `speed_source.py` | `SpeedSourceKind`, `SpeedSource` | Independent speed acquisition concern |
| `sensor.py` | `SensorPlacement`, `Sensor` | Tightly coupled sensor-and-position pair |
| `car.py` | `Car`, `TireSpec` | Vehicle geometry and tire computation |
| `analysis_window.py` | `DrivingPhase`, `AnalysisWindow` | Driving-phase enum and phase-aligned analysis chunk |
| `finding.py` | `FindingKind`, `PhaseEvidence`, `Finding` | Richest domain object (kind, classification, ranking, scoring, dB strength) |
| `report.py` | `Report` | Assembled diagnostic output |
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
   domain logic.  `OrderAssessment` and `LocalizationAssessment` delegate
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

# Domain model

## Purpose of this document

This document defines the canonical VibeSensor domain model.

It is a model reference, not a progress log, migration journal, implementation
inventory, or roadmap.

## Core domain model overview

VibeSensor is centered on one diagnostic aggregate hierarchy:

- `DiagnosticCase` is the top-level diagnostic aggregate root.
- `TestRun` is the analyzed run aggregate within a case.
- `Finding` is the surfaced run-level conclusion object within a test run.
- `Run` is the recording-time lifecycle object.
- `RunCapture` is the immutable captured-evidence object produced by one
  completed run.
- `RunSetup` is the canonical setup context used to interpret that capture.

`Car` provides case-scoped vehicle interpretive context across the entire
investigation. `OrderReferenceSpec` is a supporting typed value object within
that `Car` context for tire geometry and driveline/reference-order
interpretation. It is important internal interpretive context, but it is not a
peer aggregate or top-level headline domain concept.

Supporting typed internal objects are part of the canonical model and remain
subordinate to the aggregate hierarchy:

- run/capture interpretation context: `AnalysisSettingsSnapshot`,
  `CarSnapshot`, `RunContextSnapshot`, `RunMetadataSnapshot`
- analysis reasoning support: `StrengthMetrics`, `StrengthPeak`,
  `OrderMatchObservation`, `DrivingPhaseSummary`, `SpeedProfileSummary`,
  `LocationIntensitySummary`
- reconstruction/interpretation support: `SpeedStatsSnapshot`,
  `PhaseSummarySnapshot`, `DrivingPhaseInterval`, `DrivingPhaseSegment`

The model also draws an explicit internal performance boundary. Raw capture,
signal-processing, and other high-volume sample-processing representations may
remain simple arrays, compact records, or dict-like sample payloads inside that
performance-sensitive subsystem. Above that boundary, stable interpreted
diagnostics concepts use typed internal objects with explicit names and owned
meaning.

`Report` and `HistoryRecord` are boundary-facing derived representations, not
core diagnostic truth.

## Scope and context boundaries

The model uses explicit scope boundaries:

- case scope: `DiagnosticCase`, `Car`, `Symptom`
- car-scoped interpretive context: `OrderReferenceSpec` (owned within `Car`)
- run diagnostic scope: `TestRun`, `Finding`, `DrivingSegment`,
  `DrivingPhase`, `RecommendedAction`, `RunSuitability`, `SuitabilityCheck`,
  `SpeedProfile`, `TestPlan`
- finding scope: `ConfidenceAssessment`, `FindingEvidence`, `LocationHotspot`,
  `VibrationOrigin`
- capture lifecycle scope: `Run`, `RunStatus`
- captured evidence/setup scope: `RunCapture`, `RunSetup`, `Measurement`,
  `ConfigurationSnapshot`, `Sensor`, `SensorPlacement`, `SpeedSource`
- internal typed interpretation context: `AnalysisSettingsSnapshot`,
  `CarSnapshot`, `RunContextSnapshot`, `RunMetadataSnapshot`
- internal typed analysis/reconstruction support: `StrengthMetrics`,
  `StrengthPeak`, `OrderMatchObservation`, `DrivingPhaseSummary`,
  `DrivingPhaseInterval`, `DrivingPhaseSegment`, `SpeedStatsSnapshot`,
  `PhaseSummarySnapshot`, `SpeedProfileSummary`, `LocationIntensitySummary`
- performance-sensitive raw capture / DSP / high-volume sample-processing
  subsystem: arrays, compact records, and dict-like sample payloads retained as
  simple internal representations where per-sample object modeling would add
  unnecessary allocation and overhead
- analysis machinery: `PhaseSegment`
- boundary representations: `Report`, `HistoryRecord`, API shapes, DTOs,
  persistence shapes, export/render/template shapes, config transport shapes,
  archival/history shapes

`DiagnosticCase` scopes zero or one `Car` context (a case may exist before
car details are known), and every `TestRun`, `RunCapture`, and `RunSetup`
in that case is interpreted within that same car context when present.

## Aggregate hierarchy

The aggregate hierarchy is decisive:

- `DiagnosticCase` is the top-level aggregate root.
- `TestRun` is the analyzed run aggregate.
- `Finding` is a run-level conclusion object contained by `TestRun`.
- `Run` is capture lifecycle, not analyzed diagnostic meaning.
- `RunCapture` is immutable capture evidence from one completed `Run`.
- `RunSetup` is canonical run-setup context for capture interpretation.

Supporting typed objects (`OrderReferenceSpec`, snapshots, strength metrics,
diagnostic observations, interpretation summaries, and reconstruction support
objects) provide internal interpretation support and do not change aggregate
ownership. The raw per-sample capture and DSP path remains a separate
performance-sensitive subsystem and is not modeled as object-per-sample domain
structure.

## Canonical domain graph

```text
DiagnosticCase
  is scoped to one Car
  contains TestRun*

Car
  owns case-scoped vehicle interpretive context
  owns OrderReferenceSpec as supporting typed value context

TestRun
  contains one RunCapture
  contains DrivingSegment*
  contains Finding*

RunCapture
  references one Run (by id)
  contains one RunSetup
  contains Measurement*

RunSetup
  contains Sensor*
  contains one SpeedSource
```

Reasoning chain:

```text
Measurement -> Finding -> Report
```

## Concept categories

### Core diagnostic aggregates and entities

`DiagnosticCase`, `TestRun`, `Finding`, `Run`, `RunCapture`, `RunSetup`,
`Car`, `DrivingSegment`, `DrivingPhase`, `Measurement`, `Sensor`,
`SensorPlacement`, `SpeedSource`, `SpeedSourceKind`, `Symptom`, `TestPlan`,
`RecommendedAction`, `SpeedProfile`, `RunSuitability`, `SuitabilityCheck`,
`ConfigurationSnapshot`, `ConfidenceAssessment`, `FindingEvidence`,
`LocationHotspot`, `VibrationOrigin`, `RunStatus`.

### Domain enums

`VibrationSource`, `FindingKind`, `DrivingPhase`, `SpeedSourceKind`,
`RunStatus`.

### Domain value objects exported from Car scope

`TireSpec`, `OrderReferenceSpec`.

### Domain value objects exported from Finding scope

`Signature`, `FindingEvidence`, `VibrationOrigin`.

### Domain value objects exported from Measurement scope

`VibrationReading`.

### Supporting typed internal concepts

- car-scoped interpretive value context: `OrderReferenceSpec`
- run/capture interpretation snapshots: `AnalysisSettingsSnapshot`,
  `CarSnapshot`, `RunContextSnapshot`, `RunMetadataSnapshot`
- analysis reasoning values: `StrengthMetrics`, `StrengthPeak`,
  `OrderMatchObservation`
- diagnostics interpretation and reconstruction snapshots: `SpeedStatsSnapshot`
  (also serves diagnostics speed-profile summary role),
  `PhaseSummarySnapshot` (also serves diagnostics driving-phase summary role),
  `LocationIntensitySummary`
- reconstruction support intervals and segments: `DrivingPhaseInterval`,
  `DrivingSegment` (also serves reconstruction/diagnostics segment role)

> **Merge note (D1):** Three originally separate concepts were merged into
> existing domain types with identical fields to avoid parallel implementations:
> `DrivingPhaseSegment` → `DrivingSegment`, `SpeedProfileSummary` →
> `SpeedStatsSnapshot`, `DrivingPhaseSummary` → `PhaseSummarySnapshot`.
> `SpeedStatsSnapshot` is NOT the same concept as `SpeedProfile` (snapshot of
> speed statistics vs live behavioral model).

### Analysis machinery

`PhaseSegment` and low-level numeric/signal-processing helpers support the
model but are not canonical domain concepts. The raw capture / DSP /
high-volume sample-processing subsystem is intentionally performance-sensitive;
its per-sample transport and signal-processing representations may remain
simple arrays, compact records, or dict-like sample payloads rather than
typed object-per-sample models.

### Boundary representations

`Report`, `HistoryRecord`, API payloads, DTOs, persistence models, export/
render/template shapes, config transport shapes, and archival shapes are edge
representations.

## Object ownership rules

- `DiagnosticCase` owns case identity and run containment.
- `Car` owns case-scoped vehicle interpretive context.
- `OrderReferenceSpec` is owned within `Car` interpretive context as a
  supporting typed value object.
- `TestRun` owns run-level diagnostic interpretation and conclusion structure.
- `Finding` owns run-level conclusion semantics within a `TestRun`.
- `Run` owns recording lifecycle semantics.
- `RunCapture` owns immutable captured evidence from one completed run.
- `RunSetup` owns stable setup context used to interpret a run capture.
- `AnalysisSettingsSnapshot` is a run-attached typed snapshot/projection used
  during interpretation; it does not co-own `OrderReferenceSpec` and is not an
  alternate source of truth for car interpretive ownership.
- `CarSnapshot` and `RunContextSnapshot` own run-attached typed context
  snapshots.
- `RunMetadataSnapshot` owns the typed internal diagnostics representation of
  persisted or reconstructed run metadata; it is distinct from raw stored
  metadata maps and arbitrary metadata JSON at storage boundaries.
- `StrengthMetrics` owns typed strength-analysis semantics and contains
  `StrengthPeak` values.
- `SpeedStatsSnapshot` and `PhaseSummarySnapshot` own typed internal
  reconstruction summaries.
- `OrderMatchObservation` owns one typed internal observed match between
  measured behavior and an order/reference hypothesis.
- `DrivingPhaseSummary` owns the typed internal summary of driving-phase
  behavior.
- `DrivingPhaseInterval` owns the typed internal representation of one
  interval on the driving-phase timeline.
- `DrivingPhaseSegment` owns the typed internal representation of one
  summarized segment of phase behavior.
- `SpeedProfileSummary` owns typed internal speed-profile statistics used by
  diagnostics; it is not the same concept as the domain `SpeedProfile`.
- `LocationIntensitySummary` owns the typed internal representation of
  intensity summarized by location or observation point for diagnostics
  interpretation and report-preparation support.
- Performance-sensitive raw sample and DSP representations may remain simple
  high-volume structures inside that subsystem boundary and do not own
  diagnostic meaning.
- Boundary representations own no diagnostic meaning.

## Domain vs analysis machinery vs boundary representations

The model separates four layers:

- **Domain truth:** aggregates and domain entities centered on
  `DiagnosticCase` -> `TestRun` -> `Finding`, with capture lifecycle/evidence
  through `Run` -> `RunCapture` -> `RunSetup`.
- **Internal typed support:** stable internal interpretive and reasoning
  objects (`OrderReferenceSpec`, snapshots, strength metrics,
  `RunMetadataSnapshot`, `OrderMatchObservation`, `DrivingPhaseSummary`,
  `DrivingPhaseInterval`, `DrivingPhaseSegment`, `SpeedProfileSummary`,
  `LocationIntensitySummary`) used by diagnostics, reconstruction, and
  interpretation logic.
- **Performance-sensitive raw sample / DSP support:** high-volume raw capture,
  telemetry, and signal-processing representations that may remain simple
  arrays, compact records, or dict-like sample payloads where per-sample object
  modeling would add unnecessary allocation and overhead.
- **Boundary representations:** transport/storage/export/presentation shapes,
  including `Report` and `HistoryRecord`.

Boundary shapes are projections of domain or internal typed meaning, never the
owners of that meaning. The raw sample / DSP layer is a deliberate internal
performance boundary, not the owner of stable diagnostic interpretation.

## Strong OOP rules for this repo

Stable internal concepts with invariants, interpretation, repeated derivation,
or repeated behavioral use belong in typed internal objects.

The model distinguishes sharply between two internal layers:

- high-volume raw sample processing, where simple arrays, compact records, and
  dict-like sample payloads are intentionally retained for performance
- interpreted diagnostics concepts, where typed objects are preferred because
  they own stable meaning

API request/response shapes, payloads, DTOs, persistence models,
archival/history shapes, export/render/template shapes, and config transport
shapes may remain dict-like or payload-like at boundaries.

Raw maps may also remain inside the performance-sensitive raw capture / DSP
subsystem when they serve high-volume transport or numeric processing. Above
that boundary, interpreted summaries, observations, intervals, segments, and
reconstructed metadata belong in typed internal concepts rather than generic
dict aliases.

Boundary shapes must not become owners of diagnostic meaning.

`Car.aspects` is not the canonical internal model for vehicle interpretive
context. Vehicle interpretive context is carried by typed objects in `Car`
scope, centered on `OrderReferenceSpec`.

## Model ambiguities resolved by this document

- **`Run` vs `TestRun`:** `Run` is capture lifecycle; `TestRun` is analyzed
  diagnostic run; `RunCapture` bridges them.
- **`DrivingSegment` vs analysis segments:** `DrivingSegment` is the domain
  segment concept and also serves the diagnostics/reconstruction segment role
  (merged from `DrivingPhaseSegment`); `DrivingPhaseInterval` is a typed
  internal diagnostics/reconstruction support concept; `PhaseSegment` remains
  analysis machinery.
- **`Car` context ownership:** `Car` owns case-scoped vehicle interpretive
  context. `OrderReferenceSpec` is a supporting typed value object within that
  context.
- **`OrderReferenceSpec` ownership boundary:** `AnalysisSettingsSnapshot` may
  carry run-attached projected fields aligned with order-reference
  interpretation, but it does not co-own `OrderReferenceSpec`.
- **Typed internal support objects:** `AnalysisSettingsSnapshot`,
  `CarSnapshot`, and `RunContextSnapshot` are internal interpretation-context
  snapshots; `RunMetadataSnapshot` is the typed internal diagnostics
  representation of reconstructed run metadata; `StrengthMetrics` and
  `StrengthPeak` are internal reasoning values; `OrderMatchObservation` is a
  typed internal order/reference match observation; `DrivingPhaseInterval`
  is a typed internal diagnostics/reconstruction support object for interpreted
  phase behavior; `SpeedStatsSnapshot` and `PhaseSummarySnapshot` are internal
  reconstruction snapshots that also serve diagnostics interpretation roles
  (merged from `SpeedProfileSummary` and `DrivingPhaseSummary` respectively);
  `DrivingSegment` also serves the reconstruction segment role (merged from
  `DrivingPhaseSegment`); `SpeedStatsSnapshot` is NOT the same concept as
  `SpeedProfile`; `LocationIntensitySummary` is a typed internal
  interpretation/report-preparation support object.
- **Typed internal concepts vs boundary maps:** these supporting objects replace
  generic dict-shaped diagnostics concepts inside diagnostics and reconstruction
  logic. Raw maps may still exist at storage, transport, and render boundaries.
- **Performance boundary:** raw per-sample capture, signal-processing, and
  high-volume telemetry representations remain intentionally simple inside the
  performance-sensitive subsystem boundary. Stable higher-level diagnostics
  meaning above that boundary is carried by typed internal concepts.
- **No canonical `RunSample` object:** per-sample raw data is intentionally not
  promoted to a canonical typed object in this model.
- **`Report` vs `HistoryRecord`:** `Report` communicates conclusions;
  `HistoryRecord` archives state. Neither is core diagnostic truth.

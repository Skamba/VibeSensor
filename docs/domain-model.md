# Domain model

## Purpose of this document

This document defines the VibeSensor domain model.

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
- `RunSetup` is the setup context used to interpret that capture.

`Car` provides case-scoped vehicle interpretive context across the entire
investigation. `OrderReferenceSpec` is a supporting typed value object within
that `Car` context for tire geometry and driveline/reference-order
interpretation. It is important interpretive context, but it is not a peer
aggregate or top-level headline domain concept.

See `docs/order_tracking.md` for the shared order-band math and
matching/scoring flow built on top of `OrderReferenceSpec`.

The diagnostics / reconstruction / interpretation layer uses these supporting
typed internal concepts:

- `RunMetadataSnapshot`
- `OrderMatchObservation`
- `DrivingPhaseSummary`
- `DrivingPhaseInterval`
- `DrivingPhaseSegment`
- `SpeedProfileSummary`
- `LocationIntensitySummary`

These seven concepts are supporting typed internal diagnostics concepts. They
are not aggregate roots, not API-first models, not persistence-first models,
not report/view payloads by default, and not replacements for
`DiagnosticCase`, `TestRun`, `Finding`, `Run`, `RunCapture`, or `RunSetup`.

The model also draws an explicit internal performance boundary. Raw capture,
DSP, and other high-volume sample-processing representations may remain simple
arrays, compact records, or dict-like sample payloads inside that
performance-sensitive subsystem. No per-sample typed object is
introduced here, and `RunSample` is not part of this model. Stable diagnostics
meaning sits above that boundary in typed concepts with owned meaning.

`Report` and `HistoryRecord` are boundary-facing derived representations, not
core diagnostic truth.

See `docs/run_lifecycle.md` for the recording/persistence/post-analysis
orchestration built around `Run`.

## Scope and context boundaries

The model uses explicit scope boundaries:

- case scope: `DiagnosticCase`, `Car`, `Symptom`
- car-scoped interpretive context: `OrderReferenceSpec`
- run diagnostic scope: `TestRun`, `Finding`, `DrivingSegment`,
  `RecommendedAction`, `RunSuitability`, `SuitabilityCheck`, `SpeedProfile`,
  `TestPlan`
- finding scope: `ConfidenceAssessment`, `FindingEvidence`, `LocationHotspot`,
  `VibrationOrigin`
- capture lifecycle scope: `Run`, `RunStatus`
- captured evidence/setup scope: `RunCapture`, `RunSetup`, `Measurement`,
  `ConfigurationSnapshot`, `Sensor`, `SensorPlacement`, `SpeedSource`
- internal diagnostics / reconstruction / interpretation support:
  `RunMetadataSnapshot`, `OrderMatchObservation`, `DrivingPhaseSummary`,
  `DrivingPhaseInterval`, `DrivingPhaseSegment`, `SpeedProfileSummary`,
  `LocationIntensitySummary`
- performance-sensitive raw capture / DSP / high-volume sample-processing
  subsystem: arrays, compact records, and dict-like sample payloads retained as
  simple internal representations where per-sample object modeling would add
  unnecessary allocation and overhead
- analysis machinery: `PhaseSegment`
- boundary representations: `Report`, `HistoryRecord`, API shapes, DTOs,
  persistence shapes, export/render/template shapes, config transport shapes,
  archival/history shapes

`DiagnosticCase` scopes zero or one `Car` context (a case may exist before car
details are known), and every `TestRun`, `RunCapture`, and `RunSetup` in that
case is interpreted within that same car context when present.

## Aggregate hierarchy

The aggregate hierarchy is decisive:

- `DiagnosticCase` is the top-level aggregate root.
- `TestRun` is the analyzed run aggregate.
- `Finding` is a run-level conclusion object contained by `TestRun`.
- `Run` is capture lifecycle, not analyzed diagnostic meaning.
- `RunCapture` is immutable capture evidence from one completed `Run`.
- `RunSetup` is the run-setup context for capture interpretation.

Supporting typed diagnostics concepts provide internal interpretation support
and do not change aggregate ownership. `DrivingSegment` remains a core
run-level concept within `TestRun`. `DrivingPhaseSummary`,
`DrivingPhaseInterval`, `DrivingPhaseSegment`, `RunMetadataSnapshot`,
`OrderMatchObservation`, `SpeedProfileSummary`, and
`LocationIntensitySummary` remain supporting diagnostics-layer concepts.

## Domain graph

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
`Car`, `Symptom`, `DrivingSegment`, `Measurement`, `Sensor`,
`SensorPlacement`, `SpeedSource`, `TestPlan`, `RecommendedAction`,
`SpeedProfile`, `RunSuitability`, `SuitabilityCheck`,
`ConfigurationSnapshot`, `ConfidenceAssessment`, `LocationHotspot`.

### Domain enums

`VibrationSource`, `FindingKind`, `DrivingPhase`, `SpeedSourceKind`,
`RunStatus`.

### Domain value objects exported from Car scope

`TireSpec`, `OrderReferenceSpec`.

### Domain value objects exported from Finding scope

`Signature`, `FindingEvidence`, `VibrationOrigin`.

### Domain value objects exported from Measurement scope

`VibrationReading`.

### Supporting typed internal diagnostics concepts

- `RunMetadataSnapshot`: typed internal diagnostics/reconstruction metadata
  concept, distinct from arbitrary raw metadata JSON
- `OrderMatchObservation`: one observed match between measured behavior and an
  order/reference hypothesis
- `DrivingPhaseSummary`: typed internal summary of driving-phase behavior
- `DrivingPhaseInterval`: one interval on the driving-phase timeline
- `DrivingPhaseSegment`: one summarized segment of phase behavior
- `SpeedProfileSummary`: typed internal summary of speed-profile statistics
  used by diagnostics, distinct from `SpeedProfile`
- `LocationIntensitySummary`: typed internal summary of intensity by vehicle
  location or observation point

### Analysis machinery

`PhaseSegment` and low-level numeric/signal-processing helpers support the
model but are not domain concepts in this model. The raw capture / DSP /
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
- `DrivingSegment` owns run-level segmented driving behavior within `TestRun`.
- `SpeedProfile` owns run-level speed behavior within the core diagnostic
  model.
- `RunMetadataSnapshot` owns typed internal diagnostics/reconstruction
  metadata semantics and is distinct from raw stored metadata maps and
  arbitrary metadata JSON at storage boundaries.
- `OrderMatchObservation` owns one typed internal observed match between
  measured behavior and an order/reference hypothesis.
- `DrivingPhaseSummary` owns typed internal summary semantics for
  driving-phase behavior.
- `DrivingPhaseInterval` owns one typed internal interval on the
  driving-phase timeline.
- `DrivingPhaseSegment` owns one typed internal summarized segment of phase
  behavior.
- `SpeedProfileSummary` owns typed internal speed-profile statistics used by
  diagnostics and is distinct from the core `SpeedProfile`.
- `LocationIntensitySummary` owns typed internal intensity summary by vehicle
  location or observation point.
- Performance-sensitive raw sample and DSP representations may remain simple
  high-volume structures inside that subsystem boundary and do not own
  higher-level diagnostic meaning.
- Boundary representations own no diagnostic meaning.

## Domain vs analysis machinery vs boundary representations

The model separates four layers:

- **Domain truth:** aggregates and domain entities centered on
  `DiagnosticCase` -> `TestRun` -> `Finding`, with capture lifecycle/evidence
  through `Run` -> `RunCapture` -> `RunSetup`, and case-scoped vehicle
  interpretive context through `Car` -> `OrderReferenceSpec`.
- **Internal typed diagnostics support:** `RunMetadataSnapshot`,
  `OrderMatchObservation`, `DrivingPhaseSummary`, `DrivingPhaseInterval`,
  `DrivingPhaseSegment`, `SpeedProfileSummary`, and
  `LocationIntensitySummary`. These objects support diagnostics,
  reconstruction, and interpretation. They do not replace the aggregates and
  they are not boundary payloads.
- **Performance-sensitive raw sample / DSP support:** high-volume raw capture,
  telemetry, and signal-processing representations that may remain simple
  arrays, compact records, or dict-like sample payloads. There is no
  per-sample typed object in this model, and the raw sample / DSP layer does
  not own stable diagnostic meaning.
- **Boundary representations:** transport, storage, export, and presentation
  shapes, including `Report` and `HistoryRecord`.

Boundary shapes are projections of domain or internal typed meaning, never the
owners of that meaning. The raw sample / DSP layer is a deliberate internal
performance boundary, not the owner of stable diagnostic interpretation.

## Strong OOP rules for this repo

Stable internal concepts with meaning, repeated interpretation, repeated
derivation, or repeated normalization belong in typed objects.

The model distinguishes sharply between three representation contexts:

- high-volume raw capture / DSP / sample-processing internals, where simple
  arrays, compact records, and dict-like sample payloads are intentionally
  retained for performance
- diagnostics / reconstruction / interpretation internals, where stable
  meaning belongs in typed objects
- storage, transport, render, and archival boundaries, where payload-shaped
  representations may remain dict-like

In this model, the typed diagnostics concepts are
`RunMetadataSnapshot`, `OrderMatchObservation`, `DrivingPhaseSummary`,
`DrivingPhaseInterval`, `DrivingPhaseSegment`, `SpeedProfileSummary`, and
`LocationIntensitySummary`.

Simple representations in the raw capture / DSP subsystem must not become the
owners of higher-level diagnostic meaning. Boundary payloads must not become
the owners of diagnostic meaning. `RunSample` is not a typed object in
this model.

## Model ambiguities resolved by this document

- **`Run` vs `TestRun`:** `Run` is capture lifecycle; `TestRun` is analyzed
  diagnostic run; `RunCapture` bridges them.
- **Core `DrivingSegment` vs diagnostics `DrivingPhaseSegment`:**
  `DrivingSegment` is a core run-level domain concept within `TestRun`.
  `DrivingPhaseSegment` is a supporting typed diagnostics/reconstruction
  concept for summarized phase behavior. `PhaseSegment` remains analysis
  machinery.
- **`DrivingPhaseSummary` vs `DrivingPhaseInterval`:**
  `DrivingPhaseSummary` is a typed internal summary of driving-phase behavior;
  `DrivingPhaseInterval` is one interval on the driving-phase timeline.
- **`SpeedProfile` vs `SpeedProfileSummary`:** `SpeedProfile` is a core
  run-level domain concept; `SpeedProfileSummary` is a supporting typed
  internal diagnostics summary of speed-profile statistics.
- **`RunMetadataSnapshot` vs raw metadata maps:** `RunMetadataSnapshot` is the
  typed internal diagnostics/reconstruction metadata concept; raw metadata
  maps and arbitrary metadata JSON remain boundary or storage
  representations.
- **`OrderMatchObservation`:** `OrderMatchObservation` is one observed match
  between measured behavior and an order/reference hypothesis.
- **`LocationIntensitySummary` vs boundary intensity tables:**
  `LocationIntensitySummary` is a typed internal diagnostics summary by
  vehicle location or observation point; boundary tables or payload rows are
  projections.
- **`Car` context ownership:** `Car` owns case-scoped vehicle interpretive
  context. `OrderReferenceSpec` is a supporting typed value object within that
  context.
- **Typed internal concepts vs boundary maps:** the seven diagnostics concepts
  carry stable internal diagnostics meaning. Raw maps may still exist at
  storage, transport, and render boundaries.
- **Performance boundary:** raw per-sample capture, signal-processing, and
  high-volume telemetry representations remain intentionally simple inside the
  performance-sensitive subsystem boundary. Stable higher-level diagnostics
  meaning above that boundary is carried by typed objects.
- **No `RunSample` object:** per-sample raw data is intentionally
  not promoted to a typed object in this model.
- **`Report` vs `HistoryRecord`:** `Report` communicates conclusions;
  `HistoryRecord` archives state. Neither is core diagnostic truth.

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
  `CarSnapshot`, `RunContextSnapshot`
- analysis reasoning support: `StrengthMetrics`, `StrengthPeak`
- reconstruction/interpretation support: `SpeedStatsSnapshot`,
  `PhaseSummarySnapshot`

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
  `CarSnapshot`, `RunContextSnapshot`
- internal typed analysis/reconstruction support: `StrengthMetrics`,
  `StrengthPeak`, `SpeedStatsSnapshot`, `PhaseSummarySnapshot`
- analysis machinery: `PhaseSegment`, `AnalysisWindow`
- boundary representations: `Report`, `HistoryRecord`, API shapes, DTOs,
  persistence shapes, export/render/template shapes, config transport shapes,
  archival/history shapes

`DiagnosticCase` scopes one `Car` context, and every `TestRun`, `RunCapture`,
and `RunSetup` in that case is interpreted within that same car context.

## Aggregate hierarchy

The aggregate hierarchy is decisive:

- `DiagnosticCase` is the top-level aggregate root.
- `TestRun` is the analyzed run aggregate.
- `Finding` is a run-level conclusion object contained by `TestRun`.
- `Run` is capture lifecycle, not analyzed diagnostic meaning.
- `RunCapture` is immutable capture evidence from one completed `Run`.
- `RunSetup` is canonical run-setup context for capture interpretation.

Supporting typed objects (`OrderReferenceSpec`, snapshots, strength metrics,
reconstruction snapshots) provide internal interpretation support and do not
change aggregate ownership.

## Canonical domain graph

```text
DiagnosticCase
  is scoped to one Car
  contains TestRun*

Car
  owns case-scoped vehicle interpretive context
  owns OrderReferenceSpec as supporting typed value context

TestRun
  references one RunCapture
  contains DrivingSegment*
  contains Finding*

RunCapture
  references one Run (by id)
  contains one RunSetup
  contains Measurement*

RunSetup
  contains Sensor*
  references one SpeedSource
```

Reasoning chain:

```text
Measurement -> Finding -> Report
```

## Concept categories

### Core diagnostic aggregates and entities

`DiagnosticCase`, `TestRun`, `Finding`, `Run`, `RunCapture`, `RunSetup`,
`Car`, `DrivingSegment`, `DrivingPhase`, `Measurement`, `Sensor`,
`SensorPlacement`, `SpeedSource`, `Symptom`, `TestPlan`,
`RecommendedAction`, `SpeedProfile`, `RunSuitability`, `SuitabilityCheck`,
`ConfigurationSnapshot`, `ConfidenceAssessment`, `FindingEvidence`,
`LocationHotspot`, `VibrationOrigin`.

### Supporting typed internal concepts

- car-scoped interpretive value context: `OrderReferenceSpec`
- run/capture interpretation snapshots: `AnalysisSettingsSnapshot`,
  `CarSnapshot`, `RunContextSnapshot`
- analysis reasoning values: `StrengthMetrics`, `StrengthPeak`
- reconstruction interpretation snapshots: `SpeedStatsSnapshot`,
  `PhaseSummarySnapshot`

### Analysis machinery

`PhaseSegment`, `AnalysisWindow`, and low-level numeric/signal-processing
helpers support the model but are not canonical domain concepts.

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
- `StrengthMetrics` owns typed strength-analysis semantics and contains
  `StrengthPeak` values.
- `SpeedStatsSnapshot` and `PhaseSummarySnapshot` own typed internal
  reconstruction summaries.
- Boundary representations own no diagnostic meaning.

## Domain vs analysis machinery vs boundary representations

The model separates three layers:

- **Domain truth:** aggregates and domain entities centered on
  `DiagnosticCase` -> `TestRun` -> `Finding`, with capture lifecycle/evidence
  through `Run` -> `RunCapture` -> `RunSetup`.
- **Internal typed support:** stable internal interpretive and reasoning
  objects (`OrderReferenceSpec`, snapshots, strength metrics) used by runtime
  and analysis logic.
- **Boundary representations:** transport/storage/export/presentation shapes,
  including `Report` and `HistoryRecord`.

Boundary shapes are projections of domain or internal typed meaning, never the
owners of that meaning.

## Strong OOP rules for this repo

Stable internal concepts with invariants, interpretation, repeated derivation,
or repeated behavioral use belong in typed internal objects.

API request/response shapes, payloads, DTOs, persistence models,
archival/history shapes, export/render/template shapes, and config transport
shapes may remain dict-like or payload-like at boundaries.

Boundary shapes must not become owners of diagnostic meaning.

`Car.aspects` is not the canonical internal model for vehicle interpretive
context. Vehicle interpretive context is carried by typed objects in `Car`
scope, centered on `OrderReferenceSpec`.

## Model ambiguities resolved by this document

- **`Run` vs `TestRun`:** `Run` is capture lifecycle; `TestRun` is analyzed
  diagnostic run; `RunCapture` bridges them.
- **`DrivingSegment` vs analysis segments/windows:** `DrivingSegment` is the
  domain segment concept; `PhaseSegment` and `AnalysisWindow` are analysis
  machinery.
- **`Car` context ownership:** `Car` owns case-scoped vehicle interpretive
  context. `OrderReferenceSpec` is a supporting typed value object within that
  context.
- **`OrderReferenceSpec` ownership boundary:** `AnalysisSettingsSnapshot` may
  carry run-attached projected fields aligned with order-reference
  interpretation, but it does not co-own `OrderReferenceSpec`.
- **Typed internal support objects:** `AnalysisSettingsSnapshot`,
  `CarSnapshot`, and `RunContextSnapshot` are internal interpretation-context
  snapshots; `StrengthMetrics` and `StrengthPeak` are internal reasoning values;
  `SpeedStatsSnapshot` and `PhaseSummarySnapshot` are internal reconstruction
  snapshots.
- **`Report` vs `HistoryRecord`:** `Report` communicates conclusions;
  `HistoryRecord` archives state. Neither is core diagnostic truth.

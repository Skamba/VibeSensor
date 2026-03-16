# Domain model

## Purpose of this document

This document defines the intended domain model for VibeSensor.

It is a stable model reference. It is not a progress tracker, migration
journal, roadmap, backlog, or code audit. It states the canonical model
decisively, even when implementation is not yet perfectly aligned.

## How this document should be maintained

Change this document when the intended domain model changes.

Do not change it merely because implementation progress changes. If the code
temporarily diverges from the model, this document may note that briefly, but
it must remain a model document rather than turning into project-management or
status language. Implementation-alignment notes, migration notes, and progress
tracking belong elsewhere.

## Core domain model overview

VibeSensor is centered on a diagnostic domain model, not on a loose list of
independent nouns.

The core diagnostic domain is centered on:

- `DiagnosticCase`
- `TestRun`
- `Finding`

The model is organized around diagnostic truth:

- a `DiagnosticCase` represents one diagnostic investigation
- a `Car` provides the case-scoped interpretive context for that entire
  investigation
- `OrderReferenceSpec` is the canonical typed object for tire geometry and
  driveline or reference-order interpretation within that `Car` context
- a `TestRun` represents one analyzed diagnostic run within that case
- every `TestRun` inside a `DiagnosticCase` is interpreted within that same
  `Car` context
- a `Finding` represents run-level diagnostic conclusion content inside a
  `TestRun`
- a `Run` represents capture and recording lifecycle for a run, not analyzed
  diagnostic meaning
- a completed `Run` produces one `RunCapture`
- a `RunCapture` holds captured evidence from one completed run
- a `RunSetup` holds the canonical setup context for how that capture was
  conducted
- every `RunCapture` and `RunSetup` that feeds a `TestRun` is interpreted
  within the same case-scoped `Car` context
- `Measurement` is evidence material inside a `RunCapture`
- `DrivingSegment` is the canonical domain segmentation concept for meaningful
  portions of run evidence
- `Sensor`, `SensorPlacement`, and `SpeedSource` are part of run setup and
  evidence context

Supporting typed internal objects exist around this core, but they do not
displace it:

- `AnalysisSettingsSnapshot`, `CarSnapshot`, and `RunContextSnapshot` are
  internal typed context objects for run-attached interpretation
- `StrengthMetrics` and `StrengthPeak` are typed internal value objects for
  strength-analysis reasoning
- `SpeedStatsSnapshot` and `PhaseSummarySnapshot` are typed internal snapshot
  objects for reconstruction and interpretation support

These supporting objects are canonical internal model concepts. They are not
new aggregate roots, and they are not boundary payload shapes.

`Report` is not the center of the diagnostic model. It is a derived
representation around that model and lives in the adapter layer
(`adapters/pdf/mapping.py`).

`Car` is case-scoped interpretive context for the whole investigation. It is
not a conclusion object and not a boundary shape. Vehicle interpretive meaning
belongs on typed objects in that `Car` context, not on generic string-keyed
bags.

Boundary representations stay at the edges. API request and response shapes,
payload models, DTOs, persistence models, export and rendering shapes, config
transport shapes, and archival or history shapes may remain dict-like or
payload-like when they are storage, transport, export, or presentation
concerns.

## Scope and context boundaries

The model uses explicit scope and lifetime boundaries:

- case-scoped concepts: `DiagnosticCase`, `Car`, and `Symptom`
- car-scoped interpretive context: `OrderReferenceSpec`
- run-scoped diagnostic concepts: `TestRun`, `Finding`,
  `DrivingSegment`, `DrivingPhase`,
  `RecommendedAction`, `RunSuitability`, `SuitabilityCheck`, `SpeedProfile`,
  and `TestPlan`
- finding-scoped value objects: `ConfidenceAssessment`, `FindingEvidence`,
  `LocationHotspot`, and `VibrationOrigin`
- capture-scoped lifecycle concepts: `Run`, `RunStatus`
- capture and evidence concepts derived from completed capture: `RunCapture`,
  `RunSetup`, `Measurement`, and `ConfigurationSnapshot`
- run setup and evidence-context concepts: `Sensor`, `SensorPlacement`, and
  `SpeedSource`
- internal run and capture interpretation context: `AnalysisSettingsSnapshot`,
  `CarSnapshot`, and `RunContextSnapshot`
- internal reconstruction and interpretation support:
  `SpeedStatsSnapshot` and `PhaseSummarySnapshot`
- internal analysis reasoning support: `StrengthMetrics` and `StrengthPeak`
- analysis-machinery concepts: `PhaseSegment` and `AnalysisWindow`
- boundary-scoped derived or archival concepts: `Report` and `HistoryRecord`
- boundary transport, storage, export, and rendering shapes:
  API request and response shapes, payload models, DTOs, persistence models,
  export, render, and template shapes, config transport and boundary shapes,
  and archival or history shapes where appropriate

These scoping rules define where behavior and invariants belong.
Run-level diagnostic meaning belongs on `TestRun` and its contained
`Finding` and `DrivingSegment` objects. Capture lifecycle belongs on `Run`.
Captured evidence belongs on `RunCapture` and its `RunSetup`. Communication
and archival concerns belong on `Report`, `HistoryRecord`, and other boundary
representations.

The `Car` context propagates through the whole investigation. `DiagnosticCase`
is scoped to one `Car`, every `TestRun` in that case is interpreted within
that same `Car` context, and every `RunCapture` and `RunSetup` feeding those
runs is interpreted within that same context. Within that case-scoped
interpretive context, `OrderReferenceSpec` owns tire geometry and
driveline or reference-order interpretation. That meaning does not belong on
`Car.aspects` as a generic string-keyed internal map.

Run-attached interpretive context belongs on typed internal snapshot objects.
`AnalysisSettingsSnapshot`, `CarSnapshot`, and `RunContextSnapshot` are the
canonical internal shapes for that context. `RunContextSnapshot` contains
`AnalysisSettingsSnapshot` and optional `CarSnapshot`.

Reconstructed speed and phase summary meaning also belongs on typed internal
snapshots. `SpeedStatsSnapshot` and `PhaseSummarySnapshot` are the canonical
internal objects for that meaning, not loose summary dictionaries.

## Lifecycle and stability rules

The model uses explicit lifecycle and stability expectations:

- `Run` is mutable capture lifecycle state while recording is in progress
- `RunCapture` is immutable once produced from a completed `Run`
- `RunSetup` is stable setup context for that capture
- `TestRun` is a derived analyzed aggregate built from captured evidence
- `AnalysisSettingsSnapshot`, `CarSnapshot`, `RunContextSnapshot`,
  `SpeedStatsSnapshot`, and `PhaseSummarySnapshot` are stable internal
  snapshots of interpretation context
- `StrengthMetrics` and `StrengthPeak` are typed value objects for internal
  reasoning about analysis results
- `Report` is a derived explanatory representation
- `HistoryRecord` is an archival snapshot and boundary representation

## Aggregate hierarchy

The aggregate hierarchy is canonical:

- `DiagnosticCase` is the top-level diagnostic aggregate root.
- `TestRun` is the run-level diagnostic aggregate.
- `Finding` is the surfaced run-level conclusion object inside a `TestRun`.
- `Run` is not the main analyzed-run aggregate. It is the recording-time
  lifecycle object used to capture a run.
- `RunCapture` is the immutable captured evidence object derived from one
  completed `Run`.
- `RunSetup` is the run-setup object used by one `RunCapture`.
- `HistoryRecord` is not core diagnostic truth. It is an archival,
  persistence-facing representation tied to runs or cases.
- `Report` is a derived explanatory representation, not diagnostic truth.

Supporting typed internal value, context, and snapshot objects such as
`OrderReferenceSpec`, `AnalysisSettingsSnapshot`, `CarSnapshot`,
`RunContextSnapshot`, `StrengthMetrics`, `StrengthPeak`,
`SpeedStatsSnapshot`, and `PhaseSummarySnapshot` support interpretation inside
or around those aggregates. They are not aggregate roots.

### `DiagnosticCase`

`DiagnosticCase` is the top-level aggregate root for one diagnostic
investigation. It owns case-level identity and scopes runs to one `Car`
context.

### `TestRun`

`TestRun` is the analyzed run aggregate inside a `DiagnosticCase`. It owns the
interpreted evidence and run-level diagnostic meaning of one analyzed run. It
is derived from one `RunCapture`.

### `Finding`

`Finding` is the surfaced run-level diagnostic conclusion object inside a
`TestRun`. It is not a separate aggregate root and it does not carry case-level
consolidated meaning.

### `Run`

`Run` is the recording-time lifecycle object. It exists to represent capture
and recording lifecycle, not the analyzed run aggregate.

### `RunCapture`

`RunCapture` is the immutable captured evidence object derived from one
completed `Run`. It is the bridge between capture lifecycle and analyzed
diagnostic meaning, and it is interpreted within the same case-scoped `Car`
context as the `TestRun` derived from it.

### `RunSetup`

`RunSetup` is the canonical object for how a run was conducted. It contains the
setup context used to interpret the evidence inside a `RunCapture` and the
derived `TestRun`. It is shared interpretive context, not a conclusion object.

### `HistoryRecord`

`HistoryRecord` is an archival or persistence-facing representation of runs or
cases. It is not the primary source of diagnostic truth.

## Canonical domain graph

The canonical domain graph has two parts: the **aggregates and containment**
graph, and the **reasoning chain**.

### Aggregates and containment

```text
DiagnosticCase
  is scoped to one Car
  contains TestRun*
  owns case-level identity
  gives Car context to its TestRun*, RunCapture*, and RunSetup*

Car
  owns case-scoped vehicle interpretive context
  owns one OrderReferenceSpec for tire geometry and
    driveline/reference-order interpretation

TestRun
  references one RunCapture
  contains DrivingSegment*
  contains Finding*
  is interpreted within the case-scoped Car context

RunCapture
  references one Run (via run_id: str — no embedded Run object)
  contains one RunSetup
  contains Measurement* (structurally present, never populated in
    production — DSP pipeline operates on numpy arrays for performance)
  is interpreted within the case-scoped Car context

RunSetup
  contains Sensor*
  references one SpeedSource
  is shared interpretive context for one RunCapture and one derived TestRun
```

### Evidence and conclusions

```text
Sensor → may have one SensorPlacement
SpeedSource → qualifies speed interpretation for the run
Measurement → belongs to one RunCapture, comes from one Sensor
DrivingSegment → canonical domain segmentation concept
Finding → belongs to one TestRun, surfaced run-level conclusion
Report → derived from DiagnosticCase and TestRun
HistoryRecord → archives run or case state at the boundary
```

### Canonical reasoning chain

```text
Measurement -> Finding -> Report
```

The intended meaningful flow is:

- capture lifecycle
- captured evidence and setup
- domain aggregates and domain relationships
- typed internal interpretation objects where stable internal meaning exists
- boundary projections at the edges

The model rejects a summary-first architecture in which the meaningful flow is:

- summary, metadata, and samples
- procedural pipeline
- reconstructed domain objects
- payloads again

Payloads, summaries, DTOs, config shapes, persistence shapes, and export shapes
belong at boundaries, not at the center of the meaningful workflow, unless
they are elevated into typed internal objects that own stable meaning.

The intended evidence flow is also explicit:

- `Run` owns capture lifecycle semantics
- completed capture produces one `RunCapture`
- `RunCapture` contains captured evidence and one `RunSetup`
- `RunCapture` contains `Measurement` evidence produced by the capture process
- `TestRun` is derived from one `RunCapture`
- `Run` is not where analyzed diagnostic meaning lives
- `TestRun` is the object that gives diagnostic meaning to captured evidence
- `Report` is derived from the diagnostic model

The intended reasoning chain is also explicit:

- `Measurement` is evidence material
- `Finding` is the surfaced run-level conclusion
- `Report` is the explanatory presentation of those conclusions
- canonical chain: `Measurement -> Finding -> Report`

## Concept categories

The concept categories in this repo are:

### Core aggregates

- `DiagnosticCase`
- `TestRun`

### Core domain entities and value objects

- `Finding`
- `DrivingSegment`
- `DrivingPhase`
- `Car`
- `OrderReferenceSpec`
- `Sensor`
- `SensorPlacement`
- `SpeedSource`
- `Symptom`
- `TestPlan`
- `RecommendedAction`
- `SpeedProfile`
- `RunSuitability`
- `SuitabilityCheck`
- `ConfigurationSnapshot`

### Finding-scoped value objects

- `ConfidenceAssessment`
- `FindingEvidence`
- `LocationHotspot`
- `VibrationOrigin`

### Capture and evidence domain objects

- `RunCapture`
- `RunSetup`
- `Measurement`

### Lifecycle domain object

- `Run`

### Internal typed context and snapshot objects

- `AnalysisSettingsSnapshot`
- `CarSnapshot`
- `RunContextSnapshot`
- `SpeedStatsSnapshot`
- `PhaseSummarySnapshot`

### Internal analysis reasoning value objects

- `StrengthMetrics`
- `StrengthPeak`

### Analysis machinery and internal workflow concepts

- `PhaseSegment`
- `AnalysisWindow`

These are analysis-layer concepts, not canonical domain concepts. They are
distinct from the typed internal snapshot and value objects listed above.

### Derived domain-adjacent representations

- `Report`

`Report` is a derived explanatory representation of diagnostic conclusions. It
lives in the adapter layer (`adapters/pdf/mapping.py`), not in the domain
package.

### Boundary, adapter, archival, persistence, and payload concepts

- `HistoryRecord`
- API request and response shapes
- payload models
- DTOs
- persistence models
- export, render, and template shapes
- config transport and boundary shapes
- archival or history shapes where appropriate

These concepts exist at edges and projections. They are not the diagnostic
source of truth, and they do not own diagnostic meaning.

## Object ownership rules

The ownership rules are:

- `DiagnosticCase` owns case-level identity.
- `TestRun` owns run-level diagnostic behavior and run-level queries.
- `RunCapture` owns immutable captured evidence from one completed `Run`.
- `RunSetup` owns stable run-conduct and setup context for interpreting one
  capture and the derived `TestRun`.
- `Run` owns recording and capture lifecycle semantics, not analyzed
  diagnostic meaning.
- `Finding` owns run-level diagnostic conclusion behavior.
- `DrivingSegment` owns segment-level meaning about a meaningful portion of run
  evidence.
- `Measurement` owns captured evidence at the sample level, not diagnostic
  conclusions.
- `Car` owns vehicle-level semantics and case-scoped interpretive context
  through typed objects where that meaning is stable.
- `OrderReferenceSpec` owns tire geometry and driveline or reference-order
  interpretation, including the data needed to derive wheel, driveshaft, and
  engine reference interpretation.
- `AnalysisSettingsSnapshot` owns typed internal analysis-settings context used
  by runtime and use-case logic, and it may expose or derive an
  `OrderReferenceSpec`.
- `CarSnapshot` owns typed internal car context attached to a run.
- `RunContextSnapshot` owns the run-attached interpretive snapshot and contains
  `AnalysisSettingsSnapshot` and optional `CarSnapshot`.
- `StrengthMetrics` owns typed strength-analysis result semantics and the
  collection of `StrengthPeak` objects.
- `StrengthPeak` owns the value semantics of one strength-analysis peak.
- `SpeedStatsSnapshot` and `PhaseSummarySnapshot` own reconstructed speed and
  phase summary meaning when that meaning is used internally.
- `Sensor` and `SensorPlacement` own sensor identity and mounting or location
  semantics where practical.
- `SpeedSource` owns speed-source semantics and classification where practical.
- boundary payloads, DTOs, persistence shapes, export shapes, rendering
  shapes, config transport shapes, and archival shapes own no diagnostic
  meaning.
- low-level transforms and numerical processing should stay outside these
  objects when they are just transforms.

The model therefore expects humans to find meaningful behavior on the main
concepts that naturally own it, rather than in scattered helper code or
string-keyed internal maps.

## Domain vs analysis machinery vs boundary representations

The model draws a hard distinction between domain concepts, internal typed
context and reasoning objects, analysis machinery, and boundary
representations.

### Domain concepts

Domain concepts are the diagnostic source of truth:

- `DiagnosticCase`
- `TestRun`
- `Finding`
- `DrivingSegment`
- `DrivingPhase`
- `Measurement`
- `Car`
- `OrderReferenceSpec`
- `Sensor`
- `SensorPlacement`
- `SpeedSource`
- `RunCapture`
- `RunSetup`
- `Symptom`
- `TestPlan`
- `RecommendedAction`
- `SpeedProfile`
- `RunSuitability`
- `SuitabilityCheck`
- `ConfigurationSnapshot`
- `ConfidenceAssessment`
- `FindingEvidence`
- `LocationHotspot`
- `VibrationOrigin`

### Lifecycle domain object

- `Run`

`Run` is part of the core domain vocabulary. It is not a core aggregate, not a
boundary representation, and not the analyzed run aggregate.

Within the domain, scope still matters:

- case-scoped: `DiagnosticCase`, `Car`, `Symptom`
- car-scoped interpretive context: `OrderReferenceSpec`
- run-scoped diagnostic: `TestRun`, `Finding`,
  `DrivingSegment`, `DrivingPhase`,
  `RecommendedAction`, `RunSuitability`, `SuitabilityCheck`, `SpeedProfile`,
  `TestPlan`
- finding-scoped value objects: `ConfidenceAssessment`, `FindingEvidence`,
  `LocationHotspot`, `VibrationOrigin`
- capture-scoped lifecycle: `Run`, `RunStatus`
- capture and evidence derived from completed capture: `RunCapture`,
  `RunSetup`, `Measurement`, `ConfigurationSnapshot`
- run setup and evidence context: `Sensor`, `SensorPlacement`, `SpeedSource`

`RunSetup` belongs to setup and evidence interpretation. `Sensor`,
`SensorPlacement`, and `SpeedSource` belong to setup and evidence
interpretation as well. They do not belong to the conclusion layer.

### Internal typed context and reasoning support

These are canonical internal typed objects used by runtime, use-case, and
reconstruction flows. They are not aggregate roots, not API or persistence
payloads, and not loose internal mappings.

- `AnalysisSettingsSnapshot`
- `CarSnapshot`
- `RunContextSnapshot`
- `StrengthMetrics`
- `StrengthPeak`
- `SpeedStatsSnapshot`
- `PhaseSummarySnapshot`

Their placement is explicit:

- `AnalysisSettingsSnapshot`, `CarSnapshot`, and `RunContextSnapshot` belong
  to internal run and capture interpretation context
- `StrengthMetrics` and `StrengthPeak` belong to internal analysis and domain
  reasoning support
- `SpeedStatsSnapshot` and `PhaseSummarySnapshot` belong to internal
  reconstruction and interpretation support

These objects replace loose internal mappings when that mapping-shaped data
owns stable internal meaning. Internal `analysis_settings_snapshot` mappings,
`active_car_snapshot` mappings, strength-metrics dicts, `top_peaks` dict
lists, speed-summary mappings, and phase-summary mappings are not the intended
canonical internal model.

### Analysis machinery

Analysis machinery supports the domain model but is not itself the canonical
domain model:

- `PhaseSegment`
- `AnalysisWindow`
- low-level numeric and signal-processing helpers

### Derived domain-adjacent representations

Derived domain-adjacent representations are built from the diagnostic model but
do not replace it as the source of truth:

- `Report`

`Report` lives in the adapter layer (`adapters/pdf/mapping.py`) and its role
is explanatory communication derived from diagnostic conclusions rather than
raw transport or persistence.

### Boundary representations

Boundary representations adapt the domain to storage, transport, export, and
presentation:

- `HistoryRecord`
- API request and response shapes
- payload models
- DTOs
- persistence models
- export, render, and template data
- config transport and boundary shapes
- archival or history shapes where appropriate
- rendering-layer objects

Boundary representations may remain dict-like, payload-like, or DTO-like at
storage, transport, export, rendering, config, and archival edges. They must
not compete with the domain model or canonical internal typed objects for
ownership of diagnostic meaning.

`HistoryRecord` is distinct from `Report`: it archives run or case state for
persistence and history, rather than explaining conclusions for communication.

## Strong OOP rules for this repo

Stronger OOP in this repo does not mean "put everything in classes."

It means:

- the main workflows operate on aggregates, domain objects, and canonical
  internal typed context or value objects
- payloads, DTOs, API request and response shapes, persistence shapes, export
  and rendering shapes, config transport shapes, and archival shapes exist
  only at boundaries
- domain invariants and meaningful queries live on the relevant objects
- car context, evidence context, reasoning context, and conclusion context stay
  distinct instead of collapsing into one mixed representation
- scope and lifetime boundaries are explicit, so behavior lives at the case,
  run, capture, analysis, or boundary level where it belongs
- the meaningful flow avoids multiple competing representations of the same
  concept
- pure numeric, DSP, FFT, and stateless transforms remain functional where
  appropriate

A stable internal concept is modeled as a typed object when it has one or more
of:

- domain or interpretive invariants
- repeated behavioral use across internal workflows
- repeated parsing, normalization, or derivation logic
- meaning that would otherwise be spread across string-keyed mappings

The complement is equally important:

- payloads, DTOs, persistence shapes, API request and response shapes, export,
  render, and template shapes, config transport shapes, and archival or
  history shapes belong at boundaries and need not become domain objects

This rule is why `OrderReferenceSpec`, `AnalysisSettingsSnapshot`,
`StrengthMetrics`, `StrengthPeak`, `CarSnapshot`, `RunContextSnapshot`,
`SpeedStatsSnapshot`, and `PhaseSummarySnapshot` are canonical typed internal
objects, while boundary payloads remain boundary payloads.

The intended architecture is domain-graph first. The core workflow should move
through aggregates, entities, domain relationships, and canonical internal
typed objects, then project outward to boundary shapes only when crossing
storage, API, export, or rendering edges.

## Model ambiguities resolved by this document

This document resolves the main model tensions decisively.

### `Run` vs `TestRun`

The canonical model position is:

- `Run` = capture lifecycle object
- `RunCapture` = captured material from one completed `Run`
- `TestRun` = analyzed diagnostic run aggregate
- `TestRun` is the human-facing run concept in the diagnostic model
- the `Run` / `TestRun` ambiguity is resolved by introducing `RunCapture`
  between them

Any naming overlap in implementation does not change the model. The resolved
model position is that `TestRun` is the true diagnostic run object.

### `PhaseSegment` vs `AnalysisWindow` vs `DrivingSegment`

The canonical model position is:

- `PhaseSegment` = low-level analysis machinery
- `AnalysisWindow` = analysis-layer projection or helper concept
- `DrivingSegment` = canonical domain-level segment concept

`DrivingSegment` is the domain concept. `PhaseSegment` and `AnalysisWindow` are
not canonical domain concepts. Any overlap among them is an implementation
concern, not a model ambiguity.

### `Car` interpretive context vs `Car.aspects`

The canonical model position is:

- `Car` owns vehicle-level interpretive context through typed objects, not
  through a generic string-keyed internal `Car.aspects` map
- `OrderReferenceSpec` is the canonical typed object for tire geometry and
  driveline or reference-order interpretation
- tire dimensions, final-drive ratio, gear ratio, and tire deflection factor
  belong to `OrderReferenceSpec`
- `OrderReferenceSpec` belongs with `Car`-scoped interpretive context
- vehicle interpretive meaning does not belong on string-keyed bags of floats

If mapping-shaped car data exists at a boundary, it is a projection or
compatibility shape rather than the canonical internal model.

### Internal snapshots and reconstructed summaries

The canonical model position is:

- internal `analysis_settings_snapshot` mappings are represented as
  `AnalysisSettingsSnapshot`
- internal `active_car_snapshot` mappings are represented as `CarSnapshot`
- run-attached interpretive context is represented as `RunContextSnapshot`
- `RunContextSnapshot` contains `AnalysisSettingsSnapshot` and optional
  `CarSnapshot`
- reconstructed speed-summary mappings are represented as
  `SpeedStatsSnapshot`
- reconstructed phase-summary mappings are represented as
  `PhaseSummarySnapshot`

These are typed internal context and snapshot objects. They are not transport-
first payloads and not persistence-first shapes.

### Strength metrics and peak lists

The canonical model position is:

- internal strength-analysis result dicts are represented as `StrengthMetrics`
- internal `top_peaks` dict lists are represented as `StrengthPeak` value
  objects owned by `StrengthMetrics`
- `StrengthMetrics` owns overall strength metrics and the collection of
  `StrengthPeak` objects
- internal analysis and domain reasoning use these typed objects rather than
  loose nested mappings

### `Report`

The canonical model position is:

- `Report` is not a core diagnostic aggregate root
- `Report` is a derived explanatory representation of diagnostic conclusions
- `Report` is domain-adjacent, not the primary source of diagnostic truth
- template, export, and rendering models are edge adapters built from or around
  that derived representation
- the diagnostic source of truth is the domain graph around `DiagnosticCase`,
  `TestRun`, and `Finding`, not the report layer

`Report` must not be treated as richer than it is.

### `Report` vs `HistoryRecord`

The canonical model position is:

- `Report` explains diagnostic conclusions for communication and presentation
- `HistoryRecord` archives run or case state for persistence and history
- neither is core diagnostic truth
- they are distinct boundary-facing outcomes of the diagnostic model, not
  interchangeable representations

### Typed internal concepts vs boundary mappings

The canonical model position is:

- API request and response shapes, payload models, DTOs, persistence models,
  export, render, and template shapes, config transport shapes, and archival
  or history shapes remain boundary representations
- boundary representations may stay dict-like or payload-like
- boundary representations must not own diagnostic meaning
- typed internal objects are for stable internal concepts with invariants,
  interpretation, and repeated behavioral use

The model is not "everything becomes a class." The model is that stable
internal meaning belongs on typed internal objects, while boundary dicts remain
acceptable at storage, transport, export, rendering, config, and archival
edges.

## File-structure expectations

Key behavior-owning domain objects live under `vibesensor/domain/`. Closely
related value objects may share a file with their parent aggregate (e.g.
`FindingEvidence` and `Signature` in `finding.py`, `Symptom` in
`diagnostic_case.py`, `Measurement` in `run_capture.py`).

## Future-proofing requirement

Future feature work should extend the domain model instead of scattering logic
into:

- helper modules
- procedural stage modules
- payload conversion paths
- boundary layers
- string-keyed internal mapping bags that own stable meaning

Future-proofing means:

- stable aggregates
- explicit object relationships
- object-owned invariants
- clear domain and boundary separation
- canonical internal typed objects where stable interpretation is required
- fewer competing representations of the same concept

## Known bounded deviations

Two structural deviations from the ideal model are intentional and bounded:

1. **RunCapture.measurements: structurally present, never populated.**
   The DSP pipeline operates on numpy arrays for performance.
   `Measurement` exists in the domain graph but `RunCapture` instances
   never carry populated measurement tuples in production.

2. **`FindingPayload` as analysis-internal accumulator.** The analysis
   pipeline accumulates finding data into `FindingPayload` TypedDicts
   (`use_cases/diagnostics/_types.py`) before projecting to domain
   `Finding` objects at the boundary. This is an implementation
   convenience, not a model-level concept.

These deviations are documented here so they are not mistaken for bugs
or treated as refactoring targets without understanding the trade-offs.

## Implementation decisions (not model requirements)

- `Report` lives in the adapter layer (`adapters/pdf/mapping.py`) rather
  than in the `domain/` package because it is a derived representation
  with a single consumer (the PDF rendering pipeline).

## Brief implementation-alignment note

Implementation may still contain naming overlap, reconstruction-heavy flows, or
boundary-driven shapes that are more prominent than the model intends.

That does not change the canonical model defined here:

- `DiagnosticCase` is the top-level aggregate root
- `Car` provides case-scoped interpretive context across the whole
  investigation
- `OrderReferenceSpec` is the canonical typed owner of vehicle reference-order
  interpretation
- `TestRun` is the analyzed run aggregate
- `Run` is the recording-time lifecycle object
- `RunCapture` is the bridge between capture and diagnosis
- `RunSetup` is the canonical run-setup object
- `RunContextSnapshot` is the canonical typed run-attached interpretive
  snapshot
- `StrengthMetrics` and `StrengthPeak` are canonical typed internal analysis
  value objects
- `DrivingSegment` is the canonical domain segment concept
- `Report` is derived from the diagnostic domain and is not a core aggregate
  root

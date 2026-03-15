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
- `Diagnosis`

Related concepts such as `Observation`, `Signature`, and `Hypothesis` are part
of this diagnostic model, but they are not aggregate roots.

The model is organized around diagnostic truth:

- a `DiagnosticCase` represents one diagnostic investigation
- a `Car` provides the case-scoped interpretive context for that entire
  investigation
- a `Diagnosis` represents a consolidated case-level conclusion inside a
  `DiagnosticCase`
- a `TestRun` represents one analyzed diagnostic run within that case
- every `TestRun` inside a `DiagnosticCase` is interpreted within that same
  `Car` context
- a `DiagnosticReasoning` object represents the run-scoped reasoning model
  inside a `TestRun`
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
- `Observation`, `Signature`, and `Hypothesis` are diagnostic intermediate
  concepts that support the derivation of `Finding`

`Report` and `HistoryRecord` are not the center of the diagnostic model. They
are derived or archival representations around that model.

`Car` is case-scoped interpretive context for the whole investigation. It is
not a conclusion object and not a boundary shape.

## Scope and context boundaries

The model uses explicit scope and lifetime boundaries:

- case-scoped concepts: `DiagnosticCase`, `Diagnosis`, `Car`, and `Symptom`
- run-scoped diagnostic concepts: `TestRun`, `DiagnosticReasoning`, `Finding`,
  `DrivingSegment`, `DrivingPhase`, `Observation`, `Signature`, `Hypothesis`,
  `RecommendedAction`, `RunSuitability`, `SuitabilityCheck`, `SpeedProfile`,
  and `TestPlan`
- finding-scoped value objects: `ConfidenceAssessment`, `FindingEvidence`,
  `LocationHotspot`, and `VibrationOrigin`
- capture-scoped lifecycle concepts: `Run`, `RunStatus`
- capture and evidence concepts derived from completed capture: `RunCapture`,
  `RunSetup`, `Measurement`, and `ConfigurationSnapshot`
- run setup and evidence-context concepts: `Sensor`, `SensorPlacement`, and
  `SpeedSource`
- analysis-machinery concepts: `PhaseSegment` and `AnalysisWindow`
- boundary-scoped derived or archival concepts: `Report` and `HistoryRecord`

These scoping rules define where behavior and invariants belong. Case-level
reasoning belongs on `DiagnosticCase` and its contained `Diagnosis` objects.
Run-level diagnostic meaning belongs on `TestRun` and its contained
`DiagnosticReasoning`, `Finding`, and `DrivingSegment` objects. Capture
lifecycle belongs on `Run`. Captured evidence belongs on `RunCapture` and its
`RunSetup`. Communication and archival concerns belong on `Report` and
`HistoryRecord`.

The `Car` context propagates through the whole investigation. `DiagnosticCase`
is scoped to one `Car`, every `TestRun` in that case is interpreted within that
same `Car` context, and every `RunCapture` and `RunSetup` feeding those runs is
interpreted within that same context.

## Lifecycle and stability rules

The model uses explicit lifecycle and stability expectations:

- `Run` is mutable capture lifecycle state while recording is in progress
- `RunCapture` is immutable once produced from a completed `Run`
- `RunSetup` is stable setup context for that capture
- `TestRun` is a derived analyzed aggregate built from captured evidence
- `Diagnosis` is a derived case-level conclusion object
- `Report` is a derived explanatory representation
- `HistoryRecord` is an archival snapshot and boundary representation

## Aggregate hierarchy

The aggregate hierarchy is canonical:

- `DiagnosticCase` is the top-level diagnostic aggregate root.
- `TestRun` is the run-level diagnostic aggregate.
- `Diagnosis` is the case-level consolidated conclusion object inside
  `DiagnosticCase`.
- `DiagnosticReasoning` is the run-scoped reasoning object inside a `TestRun`.
- `Finding` is the surfaced run-level conclusion object inside a `TestRun`.
- `Run` is not the main analyzed-run aggregate. It is the recording-time
  lifecycle object used to capture a run.
- `RunCapture` is the immutable captured evidence object derived from one
  completed `Run`.
- `RunSetup` is the run-setup object used by one `RunCapture`.
- `HistoryRecord` is not core diagnostic truth. It is an archival,
  persistence-facing representation tied to runs or cases.
- `Report` is a derived explanatory representation, not diagnostic truth.

### `DiagnosticCase`

`DiagnosticCase` is the top-level aggregate root for one diagnostic
investigation. It owns case-level identity, case-level reasoning, and
cross-run reconciliation. It is scoped to one `Car` context and contains
case-level `Diagnosis` objects. That `Car` context applies to every `TestRun`,
`RunCapture`, and `RunSetup` in the case.

### `Diagnosis`

`Diagnosis` is the canonical case-level consolidated conclusion object inside a
`DiagnosticCase`. It is derived from one or more run-level `Finding` objects
across one or more `TestRun`s.

### `TestRun`

`TestRun` is the analyzed run aggregate inside a `DiagnosticCase`. It owns the
interpreted evidence and run-level diagnostic meaning of one analyzed run. It
is derived from one `RunCapture`.

### `DiagnosticReasoning`

`DiagnosticReasoning` is the run-scoped reasoning object inside a `TestRun`. It
contains the run-scoped intermediate reasoning concepts used to derive
`Finding`.

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
  contains Diagnosis*
  owns case-level identity and reasoning
  gives Car context to its TestRun*, RunCapture*, and RunSetup*

TestRun
  references one RunCapture
  contains one DiagnosticReasoning
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

### Evidence, reasoning intermediates, and conclusions

```text
Sensor → may have one SensorPlacement
SpeedSource → qualifies speed interpretation for the run
Measurement → belongs to one RunCapture, comes from one Sensor
DiagnosticReasoning → contains Observation*, Signature*, Hypothesis*
DrivingSegment → canonical domain segmentation concept
Observation → diagnostic intermediate derived from run evidence
Signature → organizes observed patterns in evidence
Hypothesis → interprets observations and signatures
Finding → belongs to one TestRun, surfaced run-level conclusion
Diagnosis → belongs to one DiagnosticCase, derived from Finding*
Report → derived from DiagnosticCase, Diagnosis, and TestRun
HistoryRecord → archives run or case state at the boundary
```

### Canonical reasoning chain

```text
Measurement -> Observation -> Signature -> Hypothesis -> Finding -> Diagnosis -> Report
```

In practice, findings are built first by the analysis pipeline and
observations/signatures/hypotheses are retroactively derived from finding
evidence — a known inversion that preserves the structural relationships while
reflecting the actual computation order.

The intended meaningful flow is:

- capture lifecycle
- captured evidence and setup
- domain aggregates and domain relationships
- boundary projections at the edges

The model rejects a summary-first architecture in which the meaningful flow is:

- summary, metadata, and samples
- procedural pipeline
- reconstructed domain objects
- payloads again

Payloads, summaries, DTOs, config shapes, persistence shapes, and export shapes
belong at boundaries, not at the center of the meaningful workflow.

The intended evidence flow is also explicit:

- `Run` owns capture lifecycle semantics
- completed capture produces one `RunCapture`
- `RunCapture` contains captured evidence and one `RunSetup`
- `RunCapture` contains `Measurement` evidence produced by the capture process
- `TestRun` is derived from one `RunCapture`
- `Run` is not where analyzed diagnostic meaning lives
- `TestRun` is the object that gives diagnostic meaning to captured evidence
- `DiagnosticCase` reconciles one or more `TestRun` into case-level
  `Diagnosis*`
- `Report` is derived from the diagnostic model

The intended reasoning chain is also explicit:

- `Measurement` is evidence material
- `Observation`, `Signature`, and `Hypothesis` are internal run-scoped
  reasoning artifacts
- `Finding` is the surfaced run-level conclusion
- `Diagnosis` is the consolidated case-level conclusion
- `Report` is the explanatory presentation of those conclusions
- canonical chain: `Measurement -> Observation -> Signature -> Hypothesis ->
  Finding -> Diagnosis -> Report`

## Concept categories

The concept categories in this repo are:

### Core aggregates

- `DiagnosticCase`
- `TestRun`

### Core domain entities and value objects

- `Diagnosis`
- `Finding`
- `DrivingSegment`
- `Car`
- `Sensor`
- `SensorPlacement`
- `SpeedSource`

### Capture and evidence domain objects

- `RunCapture`
- `RunSetup`
- `Measurement`

### Lifecycle domain object

- `Run`

### Diagnostic intermediate concepts

- `DiagnosticReasoning`
- `Observation`
- `Signature`
- `Hypothesis`

These concepts belong to the diagnostic domain, but they are not aggregate
roots, boundary shapes, or low-level analysis machinery. They exist only to
support the derivation of `Finding`.

- `DiagnosticReasoning` is the run-scoped reasoning object inside `TestRun`.
- `Observation` is a diagnostic intermediate derived from run evidence.
- `Signature` organizes or characterizes observed patterns in that evidence.
- `Hypothesis` interprets observations and signatures toward possible
  explanations.

### Analysis machinery and internal workflow concepts

- `PhaseSegment`
- `AnalysisWindow`

These are analysis-layer concepts, not canonical domain concepts.

### Derived domain-adjacent representations

- `Report`

`Report` is a derived explanatory representation of diagnostic conclusions. It
is domain-adjacent, but it is not the primary source of diagnostic truth.

### Boundary, adapter, archival, persistence, and payload concepts

- `HistoryRecord`
- persistence models
- config models
- payload models
- DTOs
- export, template, and rendering shapes

These concepts exist at edges and projections. They are not the diagnostic
source of truth.

## Object ownership rules

The ownership rules are:

- `DiagnosticCase` owns case-level identity, cross-run reconciliation, and
  case-level reasoning.
- `Diagnosis` owns consolidated case-level conclusion meaning derived from one
  or more run-level findings.
- `TestRun` owns run-level diagnostic behavior and run-level queries.
- `RunCapture` owns immutable captured evidence from one completed `Run`.
- `RunSetup` owns stable run-conduct and setup context for interpreting one
  capture and the derived `TestRun`.
- `Run` owns recording and capture lifecycle semantics, not analyzed
  diagnostic meaning.
- `DiagnosticReasoning` owns run-scoped reasoning built from evidence.
- `Observation` owns derived run-level facts that matter for reasoning.
- `Signature` owns pattern-level characterization of observed evidence.
- `Hypothesis` owns possible-explanation reasoning built from observations and
  signatures.
- `Finding` owns run-level diagnostic conclusion behavior.
- `DrivingSegment` owns segment-level meaning about a meaningful portion of run
  evidence.
- `Measurement` owns captured evidence at the sample level, not diagnostic
  conclusions.
- `Car` owns vehicle-level semantics and case-scoped interpretive context where
  practical.
- `Sensor` and `SensorPlacement` own sensor identity and mounting or location
  semantics where practical.
- `SpeedSource` owns speed-source semantics and classification where practical.
- low-level transforms and numerical processing should stay outside these
  objects when they are just transforms.

The model therefore expects humans to find meaningful behavior on the main
concepts that naturally own it, rather than in scattered helper code.

## Domain vs analysis machinery vs boundary representations

The model draws a hard distinction between domain concepts, analysis machinery,
and boundary representations.

### Domain concepts

Domain concepts are the diagnostic source of truth:

- `DiagnosticCase`
- `TestRun`
- `Diagnosis`
- `Finding`
- `DrivingSegment`
- `Measurement`
- `Car`
- `Sensor`
- `SensorPlacement`
- `SpeedSource`
- `RunCapture`
- `RunSetup`
- `DiagnosticReasoning`
- `Observation`
- `Signature`
- `Hypothesis`

### Lifecycle domain object

- `Run`

`Run` is part of the core domain vocabulary. It is not a core aggregate, not a
boundary representation, and not the analyzed run aggregate.

Within the domain, scope still matters:

- case-scoped: `DiagnosticCase`, `Diagnosis`, `Car`
- run-scoped diagnostic: `TestRun`, `DiagnosticReasoning`, `Finding`,
  `DrivingSegment`, `Observation`, `Signature`, `Hypothesis`
- capture-scoped lifecycle: `Run`
- capture and evidence derived from completed capture: `RunCapture`,
  `RunSetup`, `Measurement`
- run setup and evidence context: `Sensor`, `SensorPlacement`, `SpeedSource`

`RunSetup` belongs to setup and evidence interpretation. `Sensor`,
`SensorPlacement`, and `SpeedSource` belong to setup and evidence
interpretation as well. They do not belong to the conclusion layer.

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

`Report` is boundary-facing in use, but its role is explanatory communication
derived from diagnostic conclusions rather than raw transport or persistence.

### Boundary representations

Boundary representations adapt the domain to storage, transport, export, and
presentation:

- `HistoryRecord`
- persistence models
- config models
- payload and DTO shapes
- export and template data
- rendering-layer objects

Boundary representations must not compete with the domain model for ownership
of diagnostic meaning.

`HistoryRecord` is distinct from `Report`: it archives run or case state for
persistence and history, rather than explaining conclusions for communication.

## Strong OOP rules for this repo

Stronger OOP in this repo does not mean "put everything in classes."

It means:

- the main workflows operate on aggregates and domain objects
- payloads, DTOs, config shapes, persistence shapes, and export shapes exist
  only at boundaries
- domain invariants and meaningful queries live on the relevant objects
- car context, evidence context, reasoning context, and conclusion context stay
  distinct instead of collapsing into one mixed representation
- scope and lifetime boundaries are explicit, so behavior lives at the case,
  run, capture, analysis, or boundary level where it belongs
- the meaningful flow avoids multiple competing representations of the same
  concept
- diagnostic intermediate concepts remain inside the domain model rather than
  being flattened into boundary payloads or demoted to low-level machinery
- pure numeric, DSP, FFT, and stateless transforms remain functional where
  appropriate

The intended architecture is domain-graph first. The core workflow should move
through aggregates, entities, and domain relationships, then project outward to
boundary shapes only when crossing storage, API, export, or rendering edges.

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

### `Finding` vs `Diagnosis`

The canonical model position is:

- `Finding` is run-level
- `Diagnosis` is case-level
- `Diagnosis` is derived from one or more run-level `Finding` across the
  `DiagnosticCase`
- case-level reasoning does not overload `Finding` with both run-level and
  case-level meaning

### `PhaseSegment` vs `AnalysisWindow` vs `DrivingSegment`

The canonical model position is:

- `PhaseSegment` = low-level analysis machinery
- `AnalysisWindow` = analysis-layer projection or helper concept
- `DrivingSegment` = canonical domain-level segment concept

`DrivingSegment` is the domain concept. `PhaseSegment` and `AnalysisWindow` are
not canonical domain concepts. Any overlap among them is an implementation
concern, not a model ambiguity.

### `Report`

The canonical model position is:

- `Report` is not a core diagnostic aggregate root
- `Report` is a derived explanatory representation of diagnostic conclusions
- `Report` is domain-adjacent, not the primary source of diagnostic truth
- template, export, and rendering models are edge adapters built from or around
  that derived representation
- the diagnostic source of truth is the domain graph around `DiagnosticCase`,
  `Diagnosis`, `TestRun`, and `Finding`, not the report layer

`Report` must not be treated as richer than it is.

### `Report` vs `HistoryRecord`

The canonical model position is:

- `Report` explains diagnostic conclusions for communication and presentation
- `HistoryRecord` archives run or case state for persistence and history
- neither is core diagnostic truth
- they are distinct boundary-facing outcomes of the diagnostic model, not
  interchangeable representations

## File-structure expectations

Key behavior-owning domain objects should generally have their own file.

The file structure should mirror the domain language. Main domain objects
should not be hidden in generic catch-all modules. Small related value objects
may be grouped when appropriate. Boundary and adapter objects may live
separately from core domain files.

This file structure expectation exists to keep the model discoverable, easy to
reason about, easy to extend, and aligned with the aggregate language.

## Future-proofing requirement

Future feature work should extend the domain model instead of scattering logic
into:

- helper modules
- procedural stage modules
- payload conversion paths
- boundary layers

Future-proofing means:

- stable aggregates
- explicit object relationships
- object-owned invariants
- clear domain and boundary separation
- fewer competing representations of the same concept

## Brief implementation-alignment note

Implementation may still contain naming overlap, reconstruction-heavy flows, or
boundary-driven shapes that are more prominent than the model intends.

That does not change the canonical model defined here:

- `DiagnosticCase` is the top-level aggregate root
- `Car` provides case-scoped interpretive context across the whole
  investigation
- `Diagnosis` is the case-level consolidated conclusion object
- `TestRun` is the analyzed run aggregate
- `Run` is the recording-time lifecycle object
- `RunCapture` is the bridge between capture and diagnosis
- `RunSetup` is the canonical run-setup object
- `DiagnosticReasoning` is the run-scoped reasoning object
- `DrivingSegment` is the canonical domain segment concept
- `Report` is derived from the diagnostic domain and is not a core aggregate
  root

# Domain model

This document describes the intended domain model for VibeSensor based on the
current repository state.

It is architecture-facing on purpose: it explains which concepts are the real
domain, which concepts are still transitional, and which shapes are boundary or
workflow adapters rather than the model itself.

## Current conceptual center

The repo is no longer best described as a system centered only on simple nouns
such as vehicle, sensor, measurement, and report.

Today the intended center is a broader **diagnostic domain model** built around
these concepts:

- `DiagnosticCase`
- `TestRun`
- `Finding`
- `Hypothesis`
- `Observation`
- `Signature`

Those richer concepts now exist in `apps/server/vibesensor/domain/` and are
constructed during analysis. The current backend analysis flow builds a
canonical `TestRun` and then a `DiagnosticCase`, instead of treating the raw
summary payload as the primary internal model.

That said, the migration is not complete:

- analysis still produces and persists summary payloads
- history/report/export paths still reconstruct domain aggregates from persisted
  summaries
- some low-level analysis concepts still overlap with newer domain concepts
- `Report` is still thin and does not yet act as a rich behavior-owning
  composition root

So the honest description is:

- the intended model is a richer diagnostic domain model
- the implementation is mid-migration from payload-centered flows toward that
  domain model

## Core vocabulary

The main domain concepts in the current codebase are:

- `DiagnosticCase`: one diagnostic investigation episode for one vehicle
- `TestRun`: one analyzed diagnostic run within that case
- `Run`: the live recording-time run lifecycle object
- `Car`, `ConfigurationSnapshot`, `Symptom`, `TestPlan`
- `DrivingSegment`: a run segment meaningful for interpretation
- `Sensor`: a physical measurement source
- `Observation`: a notable fact extracted from analyzed data
- `Signature`: a pattern assembled from observations
- `Hypothesis`: a possible explanation
- `Finding`: a conclusion the system is willing to surface
- `RecommendedAction`: a next step derived from the evidence
- `SpeedProfile` and `RunSuitability`: run-quality / run-context value objects
- `FindingEvidence`, `LocationHotspot`, `ConfidenceAssessment`,
  `VibrationOrigin`: structured meaning attached to a finding

Raw summaries, report-template DTOs, history payloads, API responses, and PDF
view models are not the core domain model.

## Aggregate structure

### Top-level aggregate

`DiagnosticCase` is the intended top-level aggregate root.

In current code it owns:

- case identity (`case_id`)
- the vehicle (`car`)
- symptoms
- configuration snapshots
- the case-level `TestPlan`
- the set of `TestRun` objects
- case-level reconciled hypotheses
- case-level reconciled findings
- case-level recommended actions

`DiagnosticCase.reconcile()` already performs real cross-run behavior:

- groups hypotheses across runs
- applies explicit epistemic rules
- keeps latest surviving hypotheses
- groups findings across runs
- keeps the latest finding per finding identity
- merges recommended actions across runs

So `DiagnosticCase` is not just a DTO wrapper. It already owns meaningful
case-level behavior, even though most persisted storage still happens through
summary/history shapes.

### Run-level aggregate

`TestRun` is the analyzed run aggregate inside the case.

In current code it owns:

- the composed `Run` identity object
- `ConfigurationSnapshot`
- `DrivingSegment` instances
- `Observation` instances
- `Signature` instances
- `Hypothesis` instances
- `Finding` instances
- `top_causes`
- `SpeedProfile`
- `RunSuitability`
- `TestPlan`
- `Sensor` instances

`TestRun` also owns several human-facing run queries:

- `primary_finding`
- `primary_source`
- `primary_location`
- `effective_top_causes()`
- `has_relevant_reference_gap()`
- `top_strength_db()`
- `usable_segments`
- `recommended_actions`

That makes `TestRun`, not the persisted run row or the report, the main
analyzed run concept in the domain model.

## `Run` vs `TestRun`

This distinction must stay explicit.

### What `Run` means today

`Run` (`domain/run.py`) is the **recording-time lifecycle object**.

It owns:

- `run_id`
- `analysis_settings`
- start/stop transitions
- the in-memory `is_recording` lifecycle state

It is live only while recording. After recording stops, it is discarded by
`RunRecorder`. Persisted lifecycle then continues in the database through
`RunStatus` (`RECORDING -> ANALYZING -> COMPLETE | ERROR`).

So `Run` is not the full human-facing diagnostic run. It is the live recording
identity/lifecycle component.

### What `TestRun` means today

`TestRun` (`domain/test_run.py`) is the **analyzed run aggregate**.

It composes a `Run`, but adds the run's diagnostic meaning:

- interpreted segments
- observations
- signatures
- hypotheses
- findings
- top causes
- speed profile
- suitability
- actions

It is frozen and intended as the canonical run-level domain view after analysis.

### Which one is which

- recording-time lifecycle object: `Run`
- analyzed run aggregate: `TestRun`
- main human-facing run concept in the current domain model: `TestRun`

### Current state of the distinction

This split is intentional but still somewhat transitional because many external
surfaces still use "run" to mean the persisted history record or its summary.

The intended distinction today is:

- use `Run` when reasoning about active recording lifecycle
- use `TestRun` when reasoning about the analyzed run and its conclusions
- treat `TestRun` as the canonical domain meaning of "the run" once analysis
  exists

## Segment / window model

The current repo has three related concepts:

- `PhaseSegment`
- `AnalysisWindow`
- `DrivingSegment`

They are not equivalent, and the overlap is real.

### `PhaseSegment`

`PhaseSegment` lives in `analysis/phase_segmentation.py`.

It is low-level analysis machinery produced by the phase-segmentation step. It
tracks:

- contiguous phase boundaries
- sample indexes
- time bounds
- speed bounds
- sample count

It is used heavily inside the analysis pipeline and summary building.

This is not the canonical domain concept. It is an analysis-stage structure.

### `AnalysisWindow`

`AnalysisWindow` lives in `analysis/analysis_window.py`.

Its own docstring is explicit: it belongs to the analysis layer, not the domain
layer, because it carries array-index implementation details such as
`start_idx` and `end_idx`.

It represents a chunk of samples suitable for spectral/order analysis. In other
words, it is also low-level analysis machinery.

Today `PhaseSegment.to_analysis_window()` and
`PreparedRunData.analysis_windows` expose this shape, so `AnalysisWindow` is
best understood as an **analysis-facing projection** of segmented run data, not
as the main domain concept.

### `DrivingSegment`

`DrivingSegment` lives in `domain/driving_segment.py`.

It is the higher-level domain concept for a meaningful portion of a run. It
keeps much of the same raw boundary data as `PhaseSegment`, but adds domain
meaning such as:

- "this is a phase-aligned segment of the run"
- "this segment is or is not diagnostically usable"

Current analysis builds `DrivingSegment` instances from `PhaseSegment` via
`build_domain_driving_segments(...)`, and `TestRun` stores `DrivingSegment`
objects rather than `PhaseSegment` or `AnalysisWindow`.

### Canonical interpretation today

- low-level analysis machinery: `PhaseSegment`, `AnalysisWindow`
- higher-level domain concept: `DrivingSegment`
- canonical concept for the domain model today: `DrivingSegment`

### Current overlap and cleanup still needed

There is obvious duplication between these three types:

- all three carry similar phase/boundary information
- both `PhaseSegment` and `DrivingSegment` represent contiguous phase-aligned
  run portions
- `AnalysisWindow` is another projection over very similar data

That overlap is not fully cleaned up yet. The current intended rule should be:

- keep `PhaseSegment` and `AnalysisWindow` as analysis-pipeline machinery
- treat `DrivingSegment` as the domain-facing representation
- avoid describing `AnalysisWindow` as part of the core domain model

## `Report`

`Report` should not be overstated.

Today `Report` (`domain/report.py`) is a thin, frozen metadata wrapper for the
rendering pipeline. It currently owns only run-level metadata such as:

- `run_id`
- `lang`
- `car_name`
- `car_type`
- `report_date`
- `duration_s`
- `sample_count`
- `sensor_count`

It performs only light validation (`run_id` non-empty, `duration_s`
non-negative).

### What `Report` does not own today

It does not currently own the rich composition of report content:

- finding selection
- system-card construction
- template-level evidence shaping
- localization decisions
- PDF layout data
- report candidate ranking
- most display-oriented mapping logic

Those still live in mapping/export/template layers, especially:

- `report/mapping.py`
- `report/report_data.py`
- summary payloads plus `ReportMappingContext`
- report i18n/template helpers

### Honest description of current role

Today `Report` is a **thin metadata/domain wrapper**, not a true composition
center.

The current report pipeline works more like this:

1. persisted or live summary is projected through domain aggregates
2. report mapping reconstructs a `TestRun`-aware context
3. `Report` is built from summary metadata
4. template DTOs are assembled for PDF rendering

So the composition center is still mostly the mapping layer, not `Report`
itself.

### Intended future direction

If the model continues to mature, `Report` could become a richer composition
object over case/run conclusions. But that is not true yet and should not be
documented as if it already is.

## Relationship map

### Present intended object graph

```text
DiagnosticCase
  car: Car?
  symptoms: Symptom*
  configuration_snapshots: ConfigurationSnapshot*
  test_plan: TestPlan
  test_runs: TestRun*
  hypotheses: Hypothesis*              # reconciled case-level view
  findings: Finding*                   # reconciled case-level view
  recommended_actions: RecommendedAction*

TestRun
  run: Run
  configuration_snapshot: ConfigurationSnapshot
  sensors: Sensor*
  driving_segments: DrivingSegment*
  observations: Observation*
  signatures: Signature*
  hypotheses: Hypothesis*
  findings: Finding*
  top_causes: Finding*
  speed_profile: SpeedProfile?
  suitability: RunSuitability?
  test_plan: TestPlan

Finding
  evidence: FindingEvidence?
  location: LocationHotspot?
  confidence_assessment: ConfidenceAssessment?
  origin: VibrationOrigin?
  signatures: Signature*

Report
  run-level metadata only
```

### Relationship rules

- `DiagnosticCase` is the top-level aggregate root.
- `TestRun` is the run-level aggregate inside the case.
- `Run` is contained by `TestRun`; it is not the full analyzed aggregate.
- Run findings live first on `TestRun`.
- Case findings are reconciled from one or more `TestRun` instances by
  `DiagnosticCase.reconcile()`.
- `top_causes` on `TestRun` are a selected subset/derivation of run findings,
  not a separate parallel conclusion model.
- `Observation -> Signature -> Hypothesis -> Finding` is the intended run-level
  reasoning chain.
- `Report` is derived from run/case outputs; it does not own those conclusions.

### Measurements, sensors, and segments/windows

- `Measurement` is the raw sample value object for captured acceleration data.
- `Sensor` is the physical sensor identity/placement concept.
- raw `Measurement` objects are part of capture/processing vocabulary, but they
  are not what `DiagnosticCase` or `TestRun` currently aggregate directly.
- phase segmentation creates `PhaseSegment` values in the analysis layer.
- `PhaseSegment` may be projected to `AnalysisWindow` for analysis work.
- analysis then projects `PhaseSegment` into domain `DrivingSegment` objects for
  `TestRun`.

So the practical layering is:

`Measurement` -> analysis pipeline -> `PhaseSegment` / `AnalysisWindow` ->
`DrivingSegment` -> `TestRun`

### Reports, findings, and runs

- reports are generated per persisted run
- report mapping uses projected domain `TestRun` behavior for business
  decisions
- report template data still comes from a mix of summary payload detail and
  domain-derived decisions
- report generation does not make `Report` the domain root

### History records

History persistence is still run-centered.

- the history database stores run rows, run metadata, samples, analysis JSON,
  and status timestamps
- persisted analysis JSON now carries `case_id`
- history services reconstruct `TestRun` and `DiagnosticCase` from persisted
  summaries through `boundaries/diagnostic_case.py`
- API/history/export/report flows then re-project domain-owned fields before
  returning payloads or building PDFs

Today there is not a separate persisted case-history aggregate. History records
are persisted primarily as **run records with analysis payloads**, even though
those payloads can now reconstruct a `DiagnosticCase`.

## Domain vs workflow vs boundary concepts

The repo contains several kinds of objects. They should not be conflated.

### True domain objects

These are part of the core domain model:

- aggregates: `DiagnosticCase`, `TestRun`
- lifecycle/domain entity: `Run`
- entities/value objects: `Car`, `ConfigurationSnapshot`, `Symptom`,
  `DrivingSegment`, `Sensor`, `Observation`, `Signature`, `Hypothesis`,
  `Finding`, `RecommendedAction`, `TestPlan`, `SpeedProfile`,
  `RunSuitability`, `FindingEvidence`, `LocationHotspot`,
  `ConfidenceAssessment`, `VibrationOrigin`, `Measurement`, `VibrationReading`

### Workflow / stage objects

These are analysis-pipeline or orchestration shapes, not the core domain:

- `PhaseSegment`
- `AnalysisWindow`
- `PreparedRunData`
- finding-finalization intermediates
- report-mapping contexts

These objects are useful, but they should not be treated as the canonical human
model of diagnosis.

### Boundary representations

These are ingress/egress shapes:

- analysis summary dicts
- `FindingPayload` and related TypedDict payloads
- history API payloads (`HistoryRunPayload`, list-entry payloads)
- route/API response models
- report template DTOs
- export JSON / CSV rows

Boundary shapes may carry necessary transport or rendering detail, but they are
not where business meaning should live.

### Config / persistence / export adapters

These connect the domain to external systems:

- `HistoryDB`
- boundary decoders/projectors in `boundaries/`
- history services in `history_services/`
- report mapping and PDF rendering in `report/`
- API models and routes
- config/persistence helpers

These layers are allowed to reconstruct or project domain objects, but they
should not become the source of truth for diagnostic meaning.

## Behavior ownership

The current ownership model should be read this way:

| Concern | Current owner |
|---|---|
| Case lifecycle, cross-run reconciliation, completeness | `DiagnosticCase` |
| Active recording lifecycle | `Run` |
| Run-level interpreted evidence and run queries | `TestRun` |
| Segment meaning and diagnostic usability | `DrivingSegment` |
| Speed adequacy / speed context | `SpeedProfile` |
| Run trustworthiness | `RunSuitability` |
| Finding classification, surfacing, ranking, confidence labels | `Finding` |
| Structured finding support / localization / confidence rationale | `FindingEvidence`, `LocationHotspot`, `ConfidenceAssessment`, `VibrationOrigin` |
| Observation extraction / signature recognition / hypothesis evaluation | analysis/domain-service layer |
| Rendering, export, template shaping, API/persistence serialization | adapter layers |

## Current state vs target state

The current implementation is coherent enough to describe, but it is not fully
finished.

What is already true in code:

- analysis constructs `TestRun` and `DiagnosticCase`
- `DiagnosticCase` owns real cross-run reconciliation behavior
- `TestRun` is the main analyzed run aggregate
- `DrivingSegment` is the intended domain segment concept
- history/report/export flows project persisted summaries back through domain
  aggregates before returning or rendering
- `Finding` is already a rich domain object with real behavior

What is still transitional or overlapping:

- summary payloads remain important persistence and transport shapes
- history persistence is still run-centered, not case-centered
- `PhaseSegment`, `AnalysisWindow`, and `DrivingSegment` still overlap
- `Report` is still thin and mapping-heavy flows still do most report
  composition work
- some boundary layers still need payload fallbacks when a full aggregate is
  not available

That is the state the document should optimize for: accurate enough for humans
and future coding agents to understand what the model is today, without
pretending the migration is already complete.

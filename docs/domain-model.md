# Domain model

This document defines the domain model for VibeSensor.

It is intentionally written from first principles. The model should reflect how a
human diagnostician thinks about vibration diagnosis:

**complaint → test context → observations → signatures → hypotheses → findings → actions**

The domain model is therefore built around the **diagnostic case**, not around
summary payloads, report templates, API shapes, or persistence rows.

## Implementation status

The model below describes the **current implementation**. The backend creates
a canonical `DiagnosticCase` and `TestRun` during run analysis. Report
mapping, history services, history exports, and post-analysis persistence
reconstruct domain aggregates from persisted summaries and re-project
canonical report/history fields from the domain model before storing,
rendering, or returning payloads. Raw summary payloads remain at transport
and rendering boundaries, but backend business decisions flow through domain
aggregates rather than treating the payloads as the primary model.

## Purpose

The purpose of the domain model is to give the core of the system one coherent
source of truth for:

- what problem is being investigated
- what vehicle and configuration were tested
- what runs were performed
- what was observed in those runs
- what patterns those observations form
- what hypotheses those patterns support or weaken
- what findings are justified
- what should be done next

The core model must be expressed in domain objects, not in dict-shaped helper
structures.

## Core diagnostic vocabulary

The canonical human concepts in this system are:

- **DiagnosticCase** — one diagnostic problem for one vehicle over one episode
  of investigation
- **Vehicle** — the thing being diagnosed
- **ConfigurationSnapshot** — the relevant setup at the time of a run or case
  stage
- **Symptom** — the complaint or observed problem that motivates diagnosis
- **TestPlan** — the intended diagnostic approach
- **TestRun** — one executed diagnostic run
- **DrivingSegment** — a meaningful segment of a run used for interpretation
- **Sensor** — a physical measurement source
- **Observation** — something noticed in the data that may matter
- **Signature** — a meaningful vibration pattern assembled from observations
- **Hypothesis** — a possible explanation of the complaint
- **Finding** — a conclusion the system is willing to stand behind
- **FindingEvidence** — the structured support for a finding
- **VibrationOrigin** — the suspected source/origin of the vibration
- **LocationHotspot** — where vibration evidence is spatially concentrated
- **ConfidenceAssessment** — why confidence is high, medium, low, or withheld
- **SpeedProfile** — the speed behavior that gives context to a run
- **RunSuitability** — whether a run is trustworthy and usable for diagnosis
- **RecommendedAction** — what to inspect, verify, retest, or compare next

These are the concepts the core should be modeled around. Report/export/API
objects are derived edge forms of these concepts.

## Top-level aggregate

The natural top-level aggregate is **`DiagnosticCase`**.

`DiagnosticCase` represents the complete diagnostic problem—spanning one or
more runs and their conclusions—rather than a single run or report. It owns the
case-level identity and consistency boundaries for:

- the vehicle under diagnosis
- the complaint or symptoms being investigated
- the active or historical configuration snapshots
- the test plan
- the set of executed runs
- the evolving hypothesis set
- the finalized findings
- the recommended actions and next steps

### Current implementation

`RunAnalysis.summarize()` now builds a `DiagnosticCase` and a canonical
`TestRun` during analysis orchestration without reconstructing those objects
from a temporary summary payload. `DiagnosticCase` reconciles case-level
findings and actions from the contributing runs, and `TestRun` owns the
run-contained observations, signatures, hypotheses, findings, `SpeedProfile`,
and `RunSuitability`.

The lifecycle object **`Run`** (`domain/run.py`) remains the recording-time
identity/lifecycle component. `TestRun` composes that lifecycle object rather
than replacing it with raw ids.

What belongs on `DiagnosticCase`:

- case lifecycle and state transitions
- adding and closing test runs
- tracking whether the case has enough evidence to conclude
- reconciling findings across multiple runs
- promoting or retiring hypotheses
- producing the canonical case-level conclusion set

What does **not** belong on `DiagnosticCase`:

- FFT/DSP math
- report-template shaping
- raw API/persistence serialization
- PDF/export decisions
- ad-hoc dict traversal to recover business meaning

## Relationship map

```text
DiagnosticCase
  Vehicle
    TireSpec
  ConfigurationSnapshot*
  Symptom*
  TestPlan
    RecommendedAction*
  TestRun*
    Sensor*
    DrivingSegment*
    Observation*
    Signature*
    SpeedProfile
    RunSuitability
  Hypothesis*
  Finding*
    FindingEvidence
    VibrationOrigin
    LocationHotspot
    ConfidenceAssessment
  RecommendedAction*

Diagnostic flow:
Symptom -> TestPlan -> TestRun -> Observation -> Signature -> Hypothesis
         -> Finding -> RecommendedAction
```

Interpretation rules:

- `DiagnosticCase` is the case-level aggregate root.
- `TestRun` is a run-level aggregate within the case boundary.
- `Finding` is the conclusion object the system can present to a user.
- `FindingEvidence`, `VibrationOrigin`, `LocationHotspot`, and
  `ConfidenceAssessment` are not helper payloads; they are part of the domain
  meaning of a finding.
- `Report`, API responses, summary payloads, template DTOs, and persistence rows
  are derived boundary representations of the case and its children.

## Main domain objects

### Aggregates

| Object | Status | What it represents | What it owns | What it does **not** own |
|---|---|---|---|---|
| **Run** | ✅ Implemented | Recording-time run lifecycle and identity | start/stop state transitions, run_id, analysis_settings | findings, reports, case reconciliation |
| **DiagnosticCase** | ✅ Implemented | One diagnostic problem for one vehicle | case lifecycle, run set, reconciled hypotheses/findings, recommended actions, cross-run consistency | rendering, transport schemas, signal-processing algorithms |
| **TestRun** | ✅ Implemented | Run-level aggregate inside the case boundary | configuration snapshot, segments, observations, signatures, hypotheses, findings, speed profile, suitability, actions | rendering, transport schemas, signal-processing algorithms |
| **TestPlan** | ✅ Implemented | The intended diagnostic approach | prioritized next actions and whether more data is required | execution telemetry, report layout |

### Entities

| Object | Status | What it represents | Core behavior |
|---|---|---|---|
| **Car** | ✅ Implemented | The vehicle under diagnosis (as `Car`) | owns stable vehicle identity, tire spec, display name |
| **Sensor** | ✅ Implemented | A physical measurement source | owns identity, placement, availability, and suitability for evidence interpretation |
| **Finding** | ✅ Implemented | A justified conclusion | owns finding identity, kind, severity, actionability, confidence classification (label/tone/pct), surfacing, ranking, phase-adjusted scoring; optionally carries `FindingEvidence`, `LocationHotspot`, and `ConfidenceAssessment` domain value objects |
| **Report** | ✅ Implemented | Run-level metadata for rendering | owns run_id, lang, car info, dates, counts (thin metadata, not business logic) |
| **Symptom** | ✅ Implemented | A complaint or observed problem | owns symptom wording, onset/context, and diagnostic framing |
| **DrivingSegment** | ✅ Implemented | A meaningful portion of a run | owns segment boundaries, maneuver/phase meaning, and diagnostic usability |
| **Observation** | ✅ Implemented | A notable fact extracted from run data | owns observation type, magnitude, conditions, and signature support semantics |
| **Signature** | ✅ Implemented | A coherent vibration pattern built from observations | owns pattern identity and pattern-level consistency |
| **Hypothesis** | ✅ Implemented | A possible explanation of the complaint | owns support/contradiction state, status, and rationale |
| **RecommendedAction** | ✅ Implemented | A next diagnostic or repair step | owns action intent and priority |

### Value objects

| Object | Status | What it represents | Core behavior |
|---|---|---|---|
| **TireSpec** | ✅ Implemented | Tire geometry relevant to diagnosis | dimensional consistency and derived geometry |
| **VibrationSource** | ✅ Implemented (StrEnum) | Canonical mechanical vibration source categories | WHEEL_TIRE, DRIVELINE, ENGINE, BODY_RESONANCE, TRANSIENT_IMPACT, BASELINE_NOISE, UNKNOWN_RESONANCE, UNKNOWN |
| **FindingKind** | ✅ Implemented (StrEnum) | Finding classification category | REFERENCE, INFORMATIONAL, DIAGNOSTIC |
| **SpeedSource** | ✅ Implemented | How vehicle speed is obtained | kind (GPS/OBD2/MANUAL), effective_speed_kmh, is_live |
| **DrivingPhase** | ✅ Implemented (StrEnum) | Phase of a driving segment | CRUISE, ACCEL, DECEL, IDLE |
| **Measurement** | ✅ Implemented | A single acceleration sample | timestamp, acceleration components, vibration reading |
| **FindingEvidence** | ✅ Implemented | Structured support for a finding | evidence quality (is_strong, is_consistent, is_well_localized), match_rate, SNR, presence_ratio, burstiness, spatial_concentration |
| **LocationHotspot** | ✅ Implemented | Spatial concentration of evidence | is_well_localized, is_actionable, display_location, dominance_ratio, alternative_locations |
| **ConfidenceAssessment** | ✅ Implemented | Why confidence is high, low, or withheld | tier (A/B/C), is_conclusive, needs_more_data, reason, downgraded |
| **SpeedProfile** | ✅ Implemented | Run speed behavior as a diagnostic concept | is_adequate_for_diagnosis, known_speed_fraction, driving_fraction, has_speed_variation, supports_variable_speed_diagnosis, supports_steady_state_diagnosis |
| **RunSuitability** | ✅ Implemented | Whether a run is trustworthy enough | overall (pass/caution/fail), is_usable, failed_checks, warning_checks |
| **ConfigurationSnapshot** | ✅ Implemented | Vehicle/setup state at a specific moment | immutable diagnostic context for interpreting a run |
| **VibrationOrigin** | ✅ Implemented | Suspected source/origin conclusion | source semantics, dominance, ambiguity |

## Domain services

Not every behavior belongs on an entity or value object. Stateless or
cross-object reasoning belongs in domain services.

| Service concern | Responsibility |
|---|---|
| **Observation extraction** | Turn processed signals (FFT outputs, filtered waveforms, statistical measures, and similar algorithm outputs) into domain `Observation` objects without making business conclusions |
| **Signature recognition** | Group observations into meaningful `Signature` objects |
| **Hypothesis evaluation** | Compare signatures and evidence against possible causes and update/support `Hypothesis` objects |
| **Finding synthesis** | Turn supported hypotheses into `Finding` objects with structured evidence, origin, localization, and confidence. Currently handled by the analysis pipeline (`finalize_findings` + `select_top_causes`) rather than a standalone domain service file |
| **Case reconciliation** | Compare multiple runs inside a `DiagnosticCase` and determine whether findings strengthen, conflict, or remain inconclusive. Lives on `DiagnosticCase.reconcile()` as an aggregate method; a separate domain service file is not needed until a second consumer exists |
| **Test planning** | Determine recommended next diagnostic actions based on findings and unresolved hypotheses |

Rule: domain services may coordinate domain objects, but they must not replace
those objects with payload-driven logic.

## Canonical diagnostic flow

The intended logical flow is:

1. **Capture case context**
   - Create a `DiagnosticCase` for a vehicle and complaint.
   - Record `Symptom` objects and a `ConfigurationSnapshot`.
   - Define a `TestPlan`.

2. **Execute one or more test runs**
   - Each `TestRun` captures the run context, sensors used, and the measured
     conditions.
   - Derive a `SpeedProfile` for the run.
   - Evaluate `RunSuitability` before trusting the run for diagnosis.

3. **Produce observations**
   - Processing code computes measurements and transforms.
   - Domain/application code turns those outputs into `Observation` objects.

4. **Form signatures**
   - Related observations are assembled into `Signature` objects that represent
     recognizable vibration behavior.

5. **Evaluate hypotheses**
   - `Hypothesis` objects are supported, weakened, or rejected based on
     signatures, speed context, location evidence, and cross-run consistency.

6. **Synthesize findings**
   - A `Finding` is created only when the system is ready to make a conclusion.
   - Each finding carries `FindingEvidence`, `VibrationOrigin`,
     `LocationHotspot`, and `ConfidenceAssessment`.

7. **Decide next actions**
   - `RecommendedAction` objects follow from findings and unresolved
     hypotheses.
   - The `DiagnosticCase` owns whether the case is complete or requires more
     runs.

8. **Render or export at the edge**
   - Reports, API payloads, summaries, and persistence rows are derived from the
     domain model after conclusions exist.

## Behavior ownership

The following ownership rules are canonical:

| Concern | Owner |
|---|---|
| Case lifecycle, completeness, and cross-run consistency | `DiagnosticCase` |
| Run lifecycle and run-contained evidence boundaries | `TestRun` |
| Complaint meaning and diagnostic framing | `Symptom` |
| Segment meaning and whether a segment is diagnostically usable | `DrivingSegment` |
| Speed-related reasoning, coverage, steadiness, and speed fitness | `SpeedProfile` |
| Whether the run is trustworthy enough to interpret | `RunSuitability` |
| Evidence quality, consistency, strength, and matched support | `FindingEvidence` |
| Source/origin reasoning, dominance, and ambiguity | `VibrationOrigin` |
| Localization reasoning, strongest location, and hotspot ambiguity | `LocationHotspot` |
| Confidence rationale and withheld-confidence semantics | `ConfidenceAssessment` |
| Hypothesis support/rejection logic | `Hypothesis` plus hypothesis-evaluation services |
| Conclusion identity, severity, actionability, and user-facing conclusion meaning | `Finding` |
| Next-step intent and prioritization | `RecommendedAction` / `TestPlan` |
| Rendering, serialization, template shaping, export formatting | edge adapters |
| Pure math, DSP, FFT, and signal transforms | functional or service-style processing code |

Ownership rules:

- lifecycle belongs to the aggregate or entity that owns the lifecycle
- interpretation belongs to evidence-oriented domain objects
- cross-object reasoning belongs to explicit domain services
- rendering and serialization belong at the edges
- no object should depend on raw dict access to discover its own meaning

## Pure algorithm boundary

Pure algorithms are not domain objects just because they are important.

FFT, DSP, filtering, order extraction, statistical transforms, and other
stateless computations may remain functional or service-style. Their job is to
produce usable inputs for the domain.

They do **not** own:

- case conclusions
- hypothesis status
- run suitability decisions
- origin/localization semantics
- finding actionability

The rule is simple: **math can stay functional; meaning must belong to domain
objects.**

## Mutability guidance

- Aggregates and finalized value objects should be treated as immutable once
  published.
- Build-time mutation is allowed while assembling observations, signatures,
  evidence, or suitability checks, but the mutable builder is not the canonical
  model.
- Identity-bearing entities (`DiagnosticCase`, `TestRun`, `Hypothesis`,
  `Finding`, `RecommendedAction`) may evolve through explicit domain methods and
  state transitions.
- Value objects (`ConfigurationSnapshot`, `SpeedProfile`, `RunSuitability`,
  `FindingEvidence`, `VibrationOrigin`, `LocationHotspot`,
  `ConfidenceAssessment`, `TireSpec`) should be immutable snapshots.
- Avoid "frozen outside, mutable inside" designs where live business state is
  hidden inside lists or dicts attached to an allegedly immutable object; for
  example, a frozen dataclass that still exposes a mutable list updated after
  construction.

## Boundary and dependency rules

### Edge-only models

The following are **not** the domain model:

- API request/response models
- persistence row shapes
- TypedDict payloads
- summary dicts
- report mapping contexts
- template DTOs
- PDF view models
- export schemas

These are allowed only as ingress/egress forms.

### Boundary rules

1. Edge models are derived from domain objects on egress.
2. Edge models are decoded into domain objects on ingress.
3. Edge models may carry transport or rendering detail, but they do not own
   business meaning.
4. Business decisions must not be made by traversing summary dicts or helper
   payload shapes.
5. Reports are outputs of the domain, not the aggregate root of the domain.
6. Persistence schemas are storage contracts, not internal truth.

### Dependency rules

1. Domain modules must not depend on API, persistence, rendering, or transport
   modules.
2. Domain services may depend on domain objects and pure processing outputs.
3. Application/orchestration code may coordinate domain objects and adapters,
   but it must not replace domain behavior with mapping logic.
4. Adapter code may depend on domain/application outputs; core domain code must
   not depend on adapter DTOs.
5. Rendering and export layers may read `DiagnosticCase`, `Finding`,
   `RecommendedAction`, and related domain objects, but they must not own
   diagnostic interpretation.

## Relation of report/export/API models to the domain model

Reports, exports, summaries, and API payloads are **secondary**.

They exist to:

- present case results to a human
- persist or transport data across boundaries
- shape output for UI, API, history, or PDF consumers

They do not define what the system believes.

A report is therefore not the natural aggregate root. It is a presentation of:

- a `DiagnosticCase`
- its finalized findings
- its supporting evidence and confidence
- its recommended next actions

If a business rule changes what the system believes, it belongs in the domain
model. If a rule changes only how the result is displayed or serialized, it
belongs at the edge.

## Forbidden patterns

The following are architecture violations:

- business logic driven by summary, payload, or dict shapes
- generic summary, context, or data objects replacing real domain
  concepts such as `Observation`, `Hypothesis`, or `FindingEvidence`
- "report" objects that are really metadata bags but are treated as aggregates
- duplicate diagnostic rules split across domain objects and mapping/rendering
  helpers
- helper structures becoming the actual internal truth while domain objects are
  thin wrappers
- origin, localization, confidence, suitability, or speed reasoning living in
  payload readers instead of on `VibrationOrigin`, `LocationHotspot`,
  `ConfidenceAssessment`, `RunSuitability`, or `SpeedProfile`
- cross-run case logic living in per-run summary objects instead of on
  `DiagnosticCase`
- conclusions being produced directly from raw helper shapes without explicit
  `Observation`, `Signature`, `Hypothesis`, and `Finding` concepts
- rendering/export needs dictating the shape of the core model

## Architecture enforcement

The following guardrails are enforced by tests in
`tests/hygiene/test_domain_architecture.py`:

- Domain modules do not import boundary payload types (`FindingPayload`,
  `AnalysisSummary`) at runtime
- `Finding` is a frozen dataclass with immutable collections
- `Finding` owns confidence presentation (label_key, tone, pct_text)
- `Finding.from_payload()` populates `evidence` (`FindingEvidence`) and
  `location` (`LocationHotspot`) when the payload contains evidence_metrics
  and location_hotspot dicts
- `confidence_label()` in `top_cause_selection` delegates to
  `Finding.confidence_label()` — single source of truth
- `finalize_findings()` returns domain `Finding` objects
- `select_top_causes()` returns domain `Finding` objects
- `RunAnalysis.summarize()` publishes canonical `test_run` and
  `diagnostic_case` aggregates with `speed_profile`, `suitability`, and
  `ConfidenceAssessment` on top causes
- Report mapping context builds a domain aggregate
- history run/report services and exports project persisted summaries through
  reconstructed domain aggregates before returning API payloads, building PDFs,
  or emitting ZIP/JSON exports
- post-analysis canonicalizes summaries through the shared domain projection
  helper before storing them in history
- `non_reference_findings()` uses domain classification
- `build_system_cards()` reads confidence tone from domain `Finding`, not
  from enriched payload dicts
- `FindingEvidence`, `LocationHotspot`, `ConfidenceAssessment`, `SpeedProfile`,
  `RunSuitability`, and `SuitabilityCheck` are frozen dataclasses exported
  from `vibesensor.domain`
- `ConfidenceAssessment.tier` is consistent with `Finding.classify_confidence()`
- `DiagnosticCase`, `TestRun`, `ConfigurationSnapshot`, `Symptom`,
  `DrivingSegment`, `Observation`, `Signature`, `Hypothesis`,
  `RecommendedAction`, and `VibrationOrigin` are exported from
  `vibesensor.domain`
- explicit boundary decoders reconstruct `DiagnosticCase` / `TestRun` from
  persisted or transported summary payloads
- remaining raw payload handling is transport/rendering detail, not business
  decision-making

## Current package layout

The domain package (`vibesensor/domain/`) mirrors the human concepts above:

| File | Primary object(s) | Status |
|---|---|---|
| `__init__.py` | re-exports all domain symbols | ✅ |
| `finding.py` | `Finding`, `FindingKind`, `VibrationSource`, `speed_band_sort_key`, `speed_bin_label` | ✅ |
| `finding_evidence.py` | `FindingEvidence` | ✅ |
| `location_hotspot.py` | `LocationHotspot` | ✅ |
| `confidence_assessment.py` | `ConfidenceAssessment` | ✅ |
| `run.py` | `Run` | ✅ |
| `run_status.py` | `RunStatus`, `RUN_TRANSITIONS`, `transition_run` | ✅ |
| `run_suitability.py` | `RunSuitability`, `SuitabilityCheck` | ✅ |
| `speed_profile.py` | `SpeedProfile` | ✅ |
| `car.py` | `Car`, `TireSpec` | ✅ |
| `configuration_snapshot.py` | `ConfigurationSnapshot` | ✅ |
| `diagnostic_case.py` | `DiagnosticCase` | ✅ |
| `driving_segment.py` | `DrivingSegment` | ✅ |
| `hypothesis.py` | `Hypothesis`, `HypothesisStatus` | ✅ |
| `sensor.py` | `Sensor`, `SensorPlacement` | ✅ |
| `observation.py` | `Observation` | ✅ |
| `recommended_action.py` | `RecommendedAction` | ✅ |
| `signature.py` | `Signature` | ✅ |
| `speed_source.py` | `SpeedSource`, `SpeedSourceKind` | ✅ |
| `symptom.py` | `Symptom` | ✅ |
| `test_plan.py` | `TestPlan` | ✅ |
| `test_run.py` | `TestRun` | ✅ |
| `vibration_origin.py` | `VibrationOrigin` | ✅ |
| `driving_phase.py` | `DrivingPhase` | ✅ |
| `measurement.py` | `Measurement`, `VibrationReading` | ✅ |
| `report.py` | `Report` | ✅ |
| `services/` | observation extraction, signature recognition, hypothesis evaluation, test planning | ✅ |

The exact file split may change, but the conceptual split should not: the model
must be built around the human diagnostic concepts, not around transport or
reporting artifacts.

## Final rule

The core of VibeSensor should answer one question:

**Given this complaint, this vehicle, and these test runs, what does the system
believe, why does it believe it, and what should happen next?**

Any object that does not help answer that question in domain terms belongs at
the edge, not at the center.

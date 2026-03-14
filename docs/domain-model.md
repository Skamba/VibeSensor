# Domain model

This document defines the **target** domain model for VibeSensor.

It is intentionally written from first principles. The model should reflect how a
human diagnostician thinks about vibration diagnosis:

**complaint → test context → observations → signatures → hypotheses → findings → actions**

The domain model is therefore built around the **diagnostic case**, not around
summary payloads, report templates, API shapes, or persistence rows.

If current code differs, this document is the architectural target for later
refactoring.

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

`DiagnosticCase` represents the whole diagnostic problem, not just one run and
not just one rendered report. It owns the case-level identity and consistency
boundaries for:

- the vehicle under diagnosis
- the complaint or symptoms being investigated
- the active or historical configuration snapshots
- the test plan
- the set of executed runs
- the evolving hypothesis set
- the finalized findings
- the recommended actions and next steps

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

| Object | What it represents | What it owns | What it does **not** own |
|---|---|---|---|
| **DiagnosticCase** | One diagnostic problem for one vehicle | case lifecycle, hypothesis set, run set, findings, actions, cross-run consistency | rendering, transport schemas, signal-processing algorithms |
| **TestRun** | One executed test attempt within a case | run lifecycle, captured context, segments, observations, signatures, speed profile, suitability result | case-level conclusion reconciliation, rendering DTOs |
| **TestPlan** | The intended diagnostic approach | planned runs, comparison strategy, required evidence, next-step intent | execution telemetry, report layout |

### Entities

| Object | What it represents | Core behavior |
|---|---|---|
| **Vehicle** | The vehicle under diagnosis | owns stable vehicle identity and diagnostic-relevant physical characteristics |
| **Sensor** | A physical measurement source | owns identity, placement, availability, and suitability for evidence interpretation |
| **Symptom** | A complaint or observed problem | owns symptom wording, onset/context, and diagnostic framing |
| **DrivingSegment** | A meaningful portion of a run | owns segment boundaries, maneuver/phase meaning, and whether it is fit for a given interpretation |
| **Observation** | A notable fact extracted from run data | owns observation type, magnitude, conditions, and traceability to source measurements |
| **Signature** | A coherent vibration pattern built from observations | owns pattern identity, pattern-level consistency, and the conditions where it appears |
| **Hypothesis** | A possible explanation of the complaint | owns support/contradiction state, status, and rationale |
| **Finding** | A justified conclusion | owns finding identity, kind, severity, actionability, and conclusion wording |
| **RecommendedAction** | A next diagnostic or repair step | owns action intent, priority, and why the action follows from the findings |

### Value objects

| Object | What it represents | Core behavior |
|---|---|---|
| **TireSpec** | Tire geometry relevant to diagnosis | dimensional consistency and derived geometry |
| **ConfigurationSnapshot** | Vehicle/setup state at a specific moment | immutable diagnostic context for interpreting a run |
| **SpeedProfile** | Run speed behavior as a diagnostic concept | coverage, steadiness, usable range, and speed-related fitness signals |
| **RunSuitability** | Whether a run is trustworthy enough for analysis | pass/caution/fail outcome, suitability reasons, and structured gating semantics |
| **FindingEvidence** | Structured support for a finding | evidence quality, consistency, strength, and matched supporting evidence |
| **VibrationOrigin** | Suspected source/origin conclusion | source semantics, dominance, ambiguity, and origin-level support |
| **LocationHotspot** | Spatial concentration of evidence | strongest location, alternatives, ambiguity, confidence, and whether localization is strong enough to conclude |
| **ConfidenceAssessment** | Why confidence is high, low, or withheld | confidence level, confidence drivers, missing evidence, and caveats |

## Domain services

Not every behavior belongs on an entity or value object. Stateless or
cross-object reasoning belongs in domain services.

| Service concern | Responsibility |
|---|---|
| **Observation extraction** | Turn processed signals into domain `Observation` objects without making business conclusions |
| **Signature recognition** | Group observations into meaningful `Signature` objects |
| **Hypothesis evaluation** | Compare signatures and evidence against possible causes and update/support `Hypothesis` objects |
| **Finding synthesis** | Turn supported hypotheses into `Finding` objects with structured evidence, origin, localization, and confidence |
| **Case reconciliation** | Compare multiple runs inside a `DiagnosticCase` and determine whether findings strengthen, conflict, or remain inconclusive |

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
produce usable inputs for the domain. They do **not** own:

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
  hidden inside lists or dicts attached to an allegedly immutable object.

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
- generic `summary`, `context`, or `data` objects replacing real domain
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

## Target package shape

The target domain package should mirror the human concepts above. A clean-sheet
layout would look like this:

| File | Primary object(s) |
|---|---|
| `diagnostic_case.py` | `DiagnosticCase` |
| `vehicle.py` | `Vehicle`, `TireSpec` |
| `configuration_snapshot.py` | `ConfigurationSnapshot` |
| `symptom.py` | `Symptom` |
| `test_plan.py` | `TestPlan`, `RecommendedAction` |
| `test_run.py` | `TestRun` |
| `driving_segment.py` | `DrivingSegment` |
| `sensor.py` | `Sensor` |
| `observation.py` | `Observation` |
| `signature.py` | `Signature` |
| `hypothesis.py` | `Hypothesis` |
| `finding.py` | `Finding`, `FindingEvidence`, `VibrationOrigin`, `LocationHotspot`, `ConfidenceAssessment` |
| `speed_profile.py` | `SpeedProfile` |
| `run_suitability.py` | `RunSuitability` |
| `services/` | domain services such as signature recognition, hypothesis evaluation, and finding synthesis |

The exact file split may change, but the conceptual split should not: the model
must be built around the human diagnostic concepts, not around transport or
reporting artifacts.

## Final rule

The core of VibeSensor should answer one question:

**Given this complaint, this vehicle, and these test runs, what do we believe,
why do we believe it, and what should happen next?**

Any object that does not help answer that question in domain terms belongs at
the edge, not at the center.

# Domain model

This document is the implementation spec for the backend's domain-first
architecture. The rule is strict:

- the **core** means business logic, analysis decision-making, and domain
  operations after boundary inputs have been decoded
- the **core** uses domain objects and domain aggregates as its only source
  of truth
- payloads, TypedDicts, DTOs, and rendering data structures exist only at
  ingress and egress boundaries
- business decisions in the core must not depend on raw dict access,
  payload helper types, or rendering models

If code currently violates these rules, treat this document as the target
architecture for refactoring toward a strict OOP design.

## Canonical pipeline flow

```text
Ingress adapters
  (API payloads, protocol frames, config rows, persisted summaries)
            │
            ▼
Application / orchestration layer
  (load inputs, coordinate analysis, call mappers)
            │
            ▼
Processing / algorithm layer
  (pure math, DSP, FFT, stateless transforms)
            │
            ▼
Domain construction
  (create Finding objects and the canonical RunAnalysisResult aggregate)
            │
            ▼
Canonical domain aggregate
  RunAnalysisResult
            │
            ▼
Egress adapters
  (history serialization, API DTOs, report mapping, PDF template data)
```

Canonical flow rules:

1. Ingress adapters decode boundary data into domain inputs.
2. Application/orchestration code coordinates processing and domain
   construction, but does not replace domain behavior with payload logic.
3. Processing code stays functional and stateless; it computes evidence and
   measurements but does not own business decisions.
4. Core analysis decisions are made on `Finding` objects and on the
   `RunAnalysisResult` aggregate.
5. `RunAnalysisResult` is the canonical post-analysis state for downstream
   decisions such as classification, surfacing, ranking, and reportable
   selection.
6. Serialization shapes are derived from domain state for persistence,
   transport, and rendering. They are outputs of the core, not peer models.

## Core domain relationship map

```text
Car ───────▶ Run ───────▶ Finding ───────▶ RunAnalysisResult
             ▲                               │
Sensor ──────┘                               │ provides
  │                                          ▼
  └────▶ SensorPlacement               reportable diagnostic state

Measurement ─────▶ VibrationReading
SpeedSource ────▶ Run

Report (metadata only) ───────────────▶ report mapping adapters
```

Interpretation:

- `Run` is the lifecycle-oriented aggregate root for an in-memory or persisted
  diagnostic run.
- `Finding` is the behavior-owning diagnostic object for classification,
  actionability, surfacing, and ranking semantics.
- `RunAnalysisResult` is the **only** canonical post-analysis aggregate.
- `Report` is **not** the analyzed aggregate. In this repository it is a
  metadata/context object for report generation.
- Rendering DTOs such as `ReportTemplateData` are egress models derived from
  the aggregate and metadata; they are never internal truth.

## Architectural layers

| Layer | What belongs here | What does **not** belong here | May depend on |
|---|---|---|---|
| **Domain layer** | `vibesensor/domain/` objects, domain queries, invariants, lifecycle rules, classification/ranking/actionability logic | DTOs, TypedDict payloads, route models, persistence row shapes, PDF/template classes | Python stdlib plus shared math/unit helpers such as `vibration_strength` and `strength_bands` |
| **Application / orchestration layer** | workflow coordination, run orchestration, analysis sequencing, mapper invocation, persistence/report orchestration | raw dict-driven business rules, rendering-specific selection logic, duplicate domain rules | may depend on domain, processing, and adapters; domain must not depend on it |
| **Processing / algorithm layer** | FFT, DSP, statistical transforms, order-analysis math, phase segmentation, pure evidence generation | API DTOs, persistence DTOs, rendering models, business ownership of ranking/surfacing/classification | may depend on pure helpers and domain value types when useful; should remain stateless and adapter-free |
| **Adapter layer** | API/request/response models, TypedDict payloads, history/persistence mappers, protocol decoding, report mapping, template DTOs | canonical business truth, ranking/grouping/classification ownership | may depend on domain and application outputs; core layers must not depend on adapter DTOs |

## Canonical domain objects

### Central objects

| Object | Role | Owned behavior |
|---|---|---|
| **Run** | Aggregate root for diagnostic run lifecycle | start/stop guards, phase tracking, run-state invariants |
| **Finding** | Primary diagnostic entity/value-rich object | kind, classification, actionability, surfacing, confidence interpretation, deterministic ranking, phase-adjusted scoring, source and speed-band semantics |
| **RunAnalysisResult** | Canonical post-analysis aggregate | owns finalized `Finding` objects and top-cause selection state; exposes aggregate queries used for downstream business decisions |
| **Report** | Report metadata context only | run identity, language, car/display context, timing/report metadata; no finding selection or diagnostic ownership |

### Supporting objects

| Object | Role | Owned behavior |
|---|---|---|
| **Car** | Vehicle under test | tire geometry, circumference calculation, immutable vehicle aspects |
| **Sensor** | Accelerometer node | naming, placement presence/status |
| **SensorPlacement** | Mounting position value object | wheel/drivetrain/body categorization |
| **Measurement** | Raw sample value object | conversion to `VibrationReading` |
| **VibrationReading** | Processed vibration-strength value object | dB-oriented reading semantics and severity lookup |
| **SpeedSource** | Speed acquisition configuration | source-kind classification and speed-resolution invariants |

## Report model clarification

The word **Report** is overloaded in normal language, so this repository uses
three separate concepts:

1. **`RunAnalysisResult`** — the canonical analyzed aggregate. This owns the
   finalized diagnostic truth after analysis.
2. **`Report`** — metadata/context for a reportable run. This is effectively
   report metadata, not the diagnostic aggregate.
3. **Rendering DTOs** such as `ReportTemplateData` — egress-only structures
   shaped for template rendering and PDF generation.

Rule: if a decision changes what findings are shown, ranked, grouped,
actionable, or emphasized, that decision belongs to `Finding` or
`RunAnalysisResult`, not to `Report`, not to `ReportTemplateData`, and not to
report mapping adapters.

## Behavior ownership

| Concern | Owner |
|---|---|
| Run lifecycle and state transitions | `Run` or the relevant lifecycle aggregate/state machine in the domain |
| Finding classification (`diagnostic/reference/informational`) | `Finding` |
| Actionability, surfacing, and per-finding ranking semantics | `Finding` |
| Aggregate-level ranking, top-cause selection, and cross-finding queries | `RunAnalysisResult` |
| Report metadata and display context | `Report` |
| Serialization to history/API/rendering shapes | adapters and mappers |
| Template shaping and PDF rendering | report adapters / rendering layer |
| Pure math, DSP, FFT, signal transforms | functional code in `processing/` and `analysis/` |

Ownership rules:

- lifecycle and state transitions belong to the owning entity or aggregate
- classification, actionability, ranking, grouping, and surfacing belong to
  the owning domain object or aggregate
- serialization belongs to adapters
- rendering belongs to adapters
- pure stateless transforms stay functional and are not forced into classes

## Mutability rules

- **Value objects are immutable.**
- **Finalized domain snapshots and aggregates should be immutable where
  practical.** `Finding`, `RunAnalysisResult`, and similar finalized analysis
  outputs should behave as immutable snapshots.
- **Mutable draft/build objects may exist during construction**, but they are
  construction-time helpers, not the canonical domain model.
- **Frozen shells around mutable internals are discouraged.** If an object is
  declared frozen, its owned state should also behave immutably unless there is
  a clearly documented reason. Example: avoid a frozen dataclass that still
  owns a mutable `list` or `dict` used as live business state.
- Mutation that exists only to accumulate intermediate evidence belongs in
  builders, orchestrators, or processing helpers, not in finalized domain
  snapshots.

## Edge adapters and boundary types

These types exist only at ingress/egress boundaries:

| Type | Location | Purpose |
|---|---|---|
| `CarConfig`, `SensorConfig`, `SpeedSourceConfig` | `backend_types.py` | config/persistence DTOs mapped into domain objects |
| `SensorFrame` | `protocol.py` | protocol frame decoded before domain construction |
| `RunMetadata` | `backend_types.py` | run-level boundary/config snapshot |
| `PhaseEvidence`, `FindingPayload`, `AnalysisSummary`, `SuspectedVibrationOrigin` | `analysis/_types.py` | serialization-oriented analysis payloads and summaries |
| `ReportTemplateData` | `report/report_data.py` | rendering DTOs for templates/PDF |
| `ReportMappingContext`, summary readers, mapper functions | `report/mapping.py` | egress adapters from domain/report metadata to rendering data |
| `HistoryRunPayload` and similar transport shapes | `backend_types.py` and API modules | API/history transport forms |

Boundary rules:

- boundary payloads are decoded into domain objects on ingress
- boundary payloads are produced from domain state on egress
- boundary shapes may carry extra rendering or storage detail, but they do not
  own business decisions
- reconstruction from persistence, transport, or rendering payloads belongs in
  adapters and mappers, not on domain entities or aggregates

If a temporary compatibility constructor exists on a domain type today, treat it
as a refactoring seam to move outward, not as the desired architecture.

## Dependency rules

These rules are meant to be testable and enforceable in code review:

1. Domain modules must not import API, rendering, transport, or persistence DTO
   modules such as `backend_types.py`, `analysis/_types.py`,
   `report/report_data.py`, route payload modules, or history row/DTO helpers.
2. Core business-decision modules must not depend on boundary payload modules.
   If a module decides ranking, grouping, classification, surfacing, or
   actionability, it is core and must use domain objects.
3. Application/orchestration modules may coordinate domain objects and
   adapters, but they do not own rendering payload schemas as business truth.
4. Adapter modules may depend on domain and application outputs; domain and
   processing modules must not depend on adapter DTOs.
5. Report rendering modules may read aggregate outputs, but must not own
   finding selection, ranking, or business prioritization rules.
6. Persistence and transport schemas are derived shapes. They must not become a
   second internal model for the core.

## Forbidden patterns

The following patterns are architecture violations:

- business logic driven by repeated `.get(...)` access on dict payloads
- payload/TypedDict/helper structures used as the primary inputs to ranking,
  grouping, classification, surfacing, or actionability decisions
- rehydrating domain objects from payloads inside core business logic
- domain entities or aggregates reconstructing themselves from persistence,
  transport, or rendering payloads as a normal design pattern
- rendering adapters or template builders owning selection, prioritization, or
  diagnostic interpretation rules
- duplicate business rules split across domain and adapter layers
- keeping parallel internal "domain" and "summary payload" truth models inside
  the core and treating them as peers
- using report DTOs, API payloads, or history rows as the source of truth for
  post-analysis behavior

## Allowed exceptions

These are narrow exceptions, not alternate architecture styles:

- pure math, DSP, FFT, and other stateless transforms may remain functional
- mutable builders may exist while assembling evidence or snapshots, but the
  finalized canonical domain model must be immutable once finalized and builder
  objects must not leak into it
- temporary compatibility mappers may exist during refactors, but they belong
  at boundaries and must not become a precedent for core payload-driven design

## File layout

Each primary behavior-owning domain object lives in its own file under
`apps/server/vibesensor/domain/`:

| File | Main objects | Notes |
|---|---|---|
| `measurement.py` | `Measurement`, `VibrationReading` | raw sample and derived reading value objects |
| `run.py` | `Run` | run lifecycle aggregate root |
| `run_analysis_result.py` | `RunAnalysisResult` | canonical post-analysis aggregate |
| `speed_source.py` | `SpeedSourceKind`, `SpeedSource` | speed acquisition domain config |
| `sensor.py` | `SensorPlacement`, `Sensor` | sensor and mount semantics |
| `car.py` | `Car`, `TireSpec` | vehicle and tire geometry |
| `driving_phase.py` | `DrivingPhase` | driving phase enum used by analysis/domain decisions |
| `finding.py` | `FindingKind`, `VibrationSource`, `Finding` | finding behavior, ranking, and classification |
| `report.py` | `Report` | report metadata context only; not the analyzed aggregate |
| `run_status.py` | `RunStatus`, transitions | persisted run lifecycle state machine |

Consumers import public domain symbols from `vibesensor.domain`, not from
boundary modules.

## Modeling rules

1. **The core is domain-only.** Core decision-making uses domain objects and
   aggregates only.
2. **Serialization is derived.** Summary payloads, DTOs, and template data are
   derived from domain state and exist at the edges.
3. **Domain objects own behavior.** Do not split classification, ranking,
   selection, or lifecycle logic across helpers and adapters.
4. **Adapters translate; they do not decide.** They map, serialize, decode, and
   render.
5. **Stateless math stays functional.** Keep DSP/FFT/signal transforms as pure
   functions unless a true domain aggregate is needed.
6. **Use one canonical aggregate after analysis.** That aggregate is
   `RunAnalysisResult`.
7. **Treat `Report` precisely.** It is report metadata/context, not the
   diagnostic source of truth.

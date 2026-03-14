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
  (create SpeedProfile, RunSuitability, LocationHotspot,
   FindingEvidence, VibrationOrigin, Finding, and RunAnalysisResult)
            │
            ▼
Report-domain construction
  (derive the domain Report from RunAnalysisResult and report context)
            │
            ▼
Canonical report-domain objects
  RunAnalysisResult ──▶ Report
            │
            └── analysis truth feeds reportable state
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
4. Domain construction produces first-class domain/value objects for origin,
   localization, finding evidence, run suitability, and speed behavior before
   those concepts are serialized into payloads.
5. Core analysis decisions are made on `Finding`, `FindingEvidence`,
   `VibrationOrigin`, `LocationHotspot`, `RunSuitability`, `SpeedProfile`, and
   on the `RunAnalysisResult` aggregate.
6. `RunAnalysisResult` is the canonical post-analysis aggregate for finalized
   diagnostic truth.
7. `Report` is the canonical report-domain object derived from
   `RunAnalysisResult` plus report context. It owns reportable state for
   downstream presentation decisions before any rendering DTOs are created.
8. Serialization shapes are derived from domain state for persistence,
   transport, and rendering. They are outputs of the core, not peer models.

## Core domain relationship map

```text
Car ───────▶ Run ───────────────▶ SpeedProfile ───────▶ RunSuitability
             ▲                          │                     │
Sensor ──────┘                          │ supports            │ gates / contextualizes
  │                                     ▼                     ▼
  └────▶ SensorPlacement         LocationHotspot ───▶ VibrationOrigin

Measurement ─────▶ VibrationReading                 │
SpeedSource ────▶ Run                              │ informs
                                                   ▼
                                             FindingEvidence ───▶ Finding
                                                                      │
                                                                      ▼
                                                             RunAnalysisResult
                                                                      │
                                                                      ▼
                                                                    Report
                                                                      │
                                                                      ▼
                                                           report mapping adapters
```

Interpretation:

- `Run` is the lifecycle-oriented aggregate root for an in-memory or persisted
   diagnostic run.
- `SpeedProfile` captures the run's speed behavior as a domain concept rather
  than a loose stats bag.
- `RunSuitability` captures whether the run is trustworthy and fit for
  analysis; it is not merely a reporting checklist.
- `LocationHotspot` captures localized concentration and ambiguity of vibration
  evidence.
- `VibrationOrigin` captures source-level diagnostic meaning and origin
  ambiguity.
- `FindingEvidence` is the structured evidence owned by or attached to a
  `Finding`; it is not just a nested payload fragment.
- `Finding` is the behavior-owning diagnostic object for classification,
  actionability, surfacing, and ranking semantics.
- `RunAnalysisResult` is the canonical post-analysis aggregate for finalized
  diagnostic truth.
- `Report` is a real domain object. It is the canonical report-domain object
  built from `RunAnalysisResult` and report context, and it owns reportable
  state before rendering.
- Rendering DTOs such as `ReportTemplateData` are egress models derived from
  `Report`; they are never internal truth.

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
| **SpeedProfile** | Canonical speed-behavior snapshot for a run | speed coverage, steadiness, usable-range semantics, speed-related fitness signals for analysis decisions |
| **RunSuitability** | Canonical run-fitness decision object | whether the run is usable/trustworthy enough for analysis, structured suitability outcomes, blocking vs. cautionary checks, overall readiness semantics |
| **Finding** | Primary diagnostic entity/value-rich object | kind, classification, actionability, surfacing, confidence interpretation, deterministic ranking, phase-adjusted scoring, source and speed-band semantics |
| **VibrationOrigin** | Canonical origin-level conclusion | suspected vibration source, ambiguity between competing sources, dominance semantics, support for origin-level conclusions, origin-level confidence context |
| **FindingEvidence** | Canonical structured evidence for a finding | evidence quality, consistency, strength, matched-support semantics, confidence-support inputs, and evidence-level normalization before rendering/serialization |
| **RunAnalysisResult** | Canonical post-analysis aggregate | owns finalized `Finding` objects and top-cause selection state; exposes aggregate queries used for downstream business decisions |
| **Report** | Canonical report-domain object | owns reportable state derived from `RunAnalysisResult`, report context, surfaced findings, report-facing ordering/sections, and domain report queries prior to rendering; see [Report model clarification](#report-model-clarification) |

### Supporting objects

| Object | Role | Owned behavior |
|---|---|---|
| **Car** | Vehicle under test | tire geometry, circumference calculation, immutable vehicle aspects |
| **Sensor** | Accelerometer node | naming, placement presence/status |
| **SensorPlacement** | Mounting position value object | wheel/drivetrain/body categorization |
| **Measurement** | Raw sample value object | conversion to `VibrationReading` |
| **VibrationReading** | Processed vibration-strength value object | dB-oriented reading semantics and severity lookup |
| **SpeedSource** | Speed acquisition configuration | source-kind classification and speed-resolution invariants |
| **LocationHotspot** | Localized concentration of vibration evidence | strongest location, alternative locations, localization ambiguity, localization confidence, and whether location evidence is strong enough to support a conclusion |

### Core composition rules for the new analysis-domain objects

- `SpeedProfile` is created from aligned speed samples and phase-aware speed
  context. It is a core input into suitability, confidence, and analysis
  gating decisions.
- `RunSuitability` is derived from `SpeedProfile`, reference completeness, data
  quality, and other analysis-readiness checks. It owns the structured outcome
  of those checks.
- `LocationHotspot` is derived from localization evidence such as
  sensor-intensity concentration and matched evidence, but it owns the
  localization conclusion used by the core.
- `VibrationOrigin` is derived from ranked findings plus localization context;
  it owns the source-level conclusion, alternative source ambiguity, and
  origin-level support semantics.
- `FindingEvidence` is owned by or tightly attached to `Finding`. It carries
  structured evidence needed for confidence, consistency, and support queries.
- `RunAnalysisResult` aggregates finalized `Finding` objects together with the
  analysis-domain context needed for downstream report and orchestration
  decisions. `Report` derives from that aggregate and report context.

## Report model clarification

The term **Report** is used in multiple distinct senses across the codebase, so
this repository uses
three separate concepts:

1. **`RunAnalysisResult`** — the canonical analyzed aggregate. This owns the
   finalized diagnostic truth after analysis.
2. **`Report`** — a domain object derived from `RunAnalysisResult` and report
   context. This owns the canonical reportable state before any rendering
   adapter runs. Where current code still treats `Report` more narrowly, that
   is a legacy structure to refactor away rather than the desired model.
3. **Rendering DTOs** such as `ReportTemplateData` — egress-only structures
   shaped for template rendering and PDF generation.

Rule: if a decision changes what findings are shown, ranked, grouped,
actionable, or emphasized at the analysis level, that decision belongs to
`Finding` or `RunAnalysisResult`. If a decision shapes reportable composition
without changing diagnostic truth, it belongs to `Report`. It does not belong
to `ReportTemplateData` or report mapping adapters.

## Behavior ownership

| Concern | Owner |
|---|---|
| Run lifecycle and state transitions | `Run` or the relevant lifecycle aggregate/state machine in the domain |
| Speed coverage, steadiness, and speed-related analysis fitness | `SpeedProfile` |
| Run trustworthiness/readiness and structured suitability outcomes | `RunSuitability` |
| Localization strength, strongest location, and localization ambiguity | `LocationHotspot` |
| Source-level vibration conclusion, dominance, and origin ambiguity | `VibrationOrigin` |
| Structured evidence strength, consistency, matched support, and evidence quality | `FindingEvidence` |
| Finding classification (`diagnostic/reference/informational`) | `Finding` |
| Actionability, surfacing, and per-finding ranking semantics | `Finding` |
| Aggregate-level ranking, top-cause selection, and cross-finding queries | `RunAnalysisResult` |
| Report-domain composition, surfaced finding set, report sections, and report queries | `Report` |
| Serialization to history/API/rendering shapes | adapters and mappers |
| Template shaping and PDF rendering | report adapters / rendering layer |
| Pure math, DSP, FFT, signal transforms | functional code in `processing/` and `analysis/` |

Ownership rules:

- lifecycle and state transitions belong to the owning entity or aggregate
- speed-behavior semantics belong to `SpeedProfile`
- analysis readiness and trust decisions belong to `RunSuitability`
- localization semantics belong to `LocationHotspot`
- origin semantics belong to `VibrationOrigin`
- structured evidence semantics belong to `FindingEvidence`
- classification, actionability, ranking, grouping, and surfacing belong to
  the owning domain object or aggregate
- reportable composition belongs to `Report`
- serialization belongs to adapters
- rendering belongs to adapters
- pure stateless transforms stay functional and are not forced into classes

## Mutability rules

- **Value objects are immutable.**
- **Finalized domain snapshots and aggregates must be immutable once
  published.** `SpeedProfile`, `RunSuitability`, `LocationHotspot`,
  `VibrationOrigin`, `FindingEvidence`, `Finding`, `RunAnalysisResult`,
  `Report`, and similar finalized outputs must not expose mutable business
  state after construction.
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
| `PhaseEvidence`, `FindingPayload`, `AnalysisSummary`, `SuspectedVibrationOrigin`, `RunSuitabilityCheck`, `SpeedStats`, and payload-level location/evidence fragments | `analysis/_types.py` | serialization-oriented analysis payloads and summaries derived from domain state; not primary business truth |
| `ReportTemplateData` | `report/report_data.py` | rendering DTOs for templates/PDF |
| `ReportMappingContext`, summary readers, mapper functions | `report/mapping.py` | egress adapters from domain report objects to rendering data |
| `HistoryRunPayload` and similar transport shapes | `backend_types.py` and API modules | API/history transport forms |

Boundary rules:

- boundary payloads are decoded into domain objects on ingress
- boundary payloads are produced from domain state on egress
- boundary shapes may carry extra rendering or storage detail, but they do not
  own business decisions
- payload forms such as `SuspectedVibrationOrigin`, `RunSuitabilityCheck`,
  `SpeedStats`, nested `location_hotspot`, or finding evidence dict fragments
  are edge representations of `VibrationOrigin`, `RunSuitability`,
  `SpeedProfile`, `LocationHotspot`, and `FindingEvidence`
- reconstruction from persistence, transport, or rendering payloads belongs in
  adapters and mappers, not on domain entities or aggregates
- if a legacy factory such as `RunAnalysisResult.from_summary()` still exists,
  treat it as a boundary compatibility shim only; core business-decision code
  must not rely on payload-driven reconstruction as a standard architectural
  pattern

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
5. Report rendering modules may read `Report` and upstream aggregate outputs,
   but must not own finding selection, ranking, or business prioritization
   rules.
6. Persistence and transport schemas are derived shapes. They must not become a
   second internal model for the core.

## Forbidden patterns

The following patterns are architecture violations:

- business logic driven by repeated `.get(...)` access on dict payloads
- payload/TypedDict/helper structures used as the primary inputs to ranking,
  grouping, classification, surfacing, or actionability decisions
- leaving origin, localization, evidence, suitability, or speed behavior as
  loose dict-driven business logic instead of first-class domain/value objects
- rehydrating domain objects from payloads inside core business logic
- domain entities or aggregates reconstructing themselves from persistence,
  transport, or rendering payloads as a normal design pattern
- rendering adapters or template builders owning selection, prioritization, or
  diagnostic interpretation rules
- treating `Report` as a mere metadata bag while report-domain behavior lives in
  mappers or template DTOs
- duplicate business rules split across domain and adapter layers
- keeping parallel internal "domain" and "summary payload" truth models inside
  the core and treating them as peers
- using report DTOs, API payloads, or history rows as the source of truth for
  post-analysis behavior
- treating `SuspectedVibrationOrigin`, `RunSuitabilityCheck`, `SpeedStats`,
  payload `location_hotspot`, or nested finding-evidence dicts as the canonical
  internal model after domain construction

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
| `speed_profile.py` | `SpeedProfile` | canonical speed-behavior object for coverage, steadiness, and speed fitness |
| `run_suitability.py` | `RunSuitability` | canonical run-readiness and trust object |
| `speed_source.py` | `SpeedSourceKind`, `SpeedSource` | speed acquisition domain config |
| `sensor.py` | `SensorPlacement`, `Sensor` | sensor and mount semantics |
| `car.py` | `Car`, `TireSpec` | vehicle and tire geometry |
| `driving_phase.py` | `DrivingPhase` | driving phase enum used by analysis/domain decisions |
| `location_hotspot.py` | `LocationHotspot` | localization-domain object for strongest location and ambiguity |
| `vibration_origin.py` | `VibrationOrigin` | source/origin-domain object for origin-level conclusions |
| `finding_evidence.py` | `FindingEvidence` | structured evidence object associated with `Finding` |
| `finding.py` | `FindingKind`, `VibrationSource`, `Finding` | finding behavior, ranking, classification, and ownership of `FindingEvidence` |
| `report.py` | `Report` | report-domain object derived from `RunAnalysisResult`; rendering DTOs remain adapter concerns |
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
   Do not leave source/origin, localization, evidence-quality, run-suitability,
   or speed-profile logic in payload readers.
4. **Adapters translate; they do not decide.** They map, serialize, decode, and
   render.
5. **Stateless math stays functional.** Keep DSP/FFT/signal transforms as pure
   functions unless a true domain aggregate is needed.
6. **Use one canonical aggregate after analysis.** That aggregate is
   `RunAnalysisResult`.
7. **Treat `Report` precisely.** It is a real domain object for reportable
   state derived from `RunAnalysisResult`; it is not a mere metadata bag and it
   is not a rendering DTO.
8. **Model analysis context explicitly.** `VibrationOrigin`, `LocationHotspot`,
   `FindingEvidence`, `RunSuitability`, and `SpeedProfile` are first-class
   domain/value objects in the target architecture, not convenience wrappers
   around summary payload fields.

# Final report redesign: Verdict + Workbook

> **Status:** Active
> **Use:** Current report/PDF design guidance for the verdict page, appendices,
> vocabulary, and history-side preparation responsibilities.

## Baseline design being extended

This design explicitly extends the last-selected **“Verdict + Workbook”** direction rather than replacing it.

The baseline being preserved is:

- a **strict one-page primary summary** comes first
- the main report remains a **single PDF** with appendices, not a new product surface
- page 1 stays centered on a **decisive verdict**, a **vehicle hotspot map**, and **top next actions**
- deeper material stays behind page 1 in appendices:
  - **Appendix A — Technician Worksheet**
  - **Appendix B — Sensor Topology**
  - **Appendix C — Evidence Detail**
  - **Appendix D — Run Context**

This final design evolves that baseline in five concrete ways:

1. page 1 is reduced to **four reading zones** plus a footer
2. page 1 uses **one trust language system**: `Action status`
3. source, location, and alternative-candidate language are **explicitly separated**
4. appendices get **non-overlapping jobs**
5. new derived semantics are treated as **history-side preparation work**, not renderer-only layout work

## Problem being solved

The current report is informative but structurally conflicted.

A real report generated in this repo showed these weaknesses:

- page 1 wastes too much space on metadata and not enough on the decision
- confidence and caveats exist, but they are not grouped tightly enough to support fast action
- source, location, and evidence are visible, but not labeled clearly enough for non-experts or technicians
- the evidence page contains useful material, but the proof chain is not obvious enough for workshop trust
- the report underuses current insight payloads, especially sensor intensity, suitability, and supporting evidence context

The redesign solves this by making page 1 a **decision surface** and the appendices **proof/workflow surfaces**.

## Target users

### Primary target

- **DIY owner or general user** who wants a likely source, a first inspection location, and an answer to “should I act on this run yet?”

### Secondary targets

- **Garage technician** who needs a worksheet and proof trail
- **Advanced multi-sensor user** who wants spatial evidence strong enough to justify the location call

### Out of scope for this redesign

- repeat-run comparison / repair-delta reporting
- replacing the PDF with a new app-native report system
- interactive diagnostic exploration inside the report

## Primary use cases

1. A user records a run, opens History, and downloads the report for a likely diagnosis.
2. A technician reads the same PDF and follows a structured inspection path.
3. A multi-sensor user checks whether the dominant corner really outranks the alternatives.
4. A weak run tells the user to recapture data before acting.

## Core design principles

1. **Decision first.** Page 1 answers the question before it explains the evidence.
2. **One trust system.** Page 1 uses `Action status` only; all deeper trust detail is appendix material.
3. **Nouns must stay clean.** Source is not location, and location is not proof.
4. **Spatial proof is the signature.** The report should visibly leverage the multi-sensor model.
5. **Each appendix gets one job.** No appendix should feel like a dump for leftover content.
6. **Renderer stays thin.** Any new semantic outputs must be derived on the history/preparation side, not in PDF drawing code.

## End-to-end flow

1. User records a run.
2. The run appears in **History** with the current preview/insight loading flow.
3. User downloads the PDF.
4. Page 1 gives the decision.
5. Appendix A gives workflow.
6. Appendix B gives spatial proof.
7. Appendix C gives the evidence trail.
8. Appendix D gives traceability.

Wave-1 scope note:

- this redesign is implemented primarily in the **PDF/report pipeline**
- aligning History preview vocabulary is desirable, but it is **not required for wave 1** unless it can reuse the same copy without new API or backend work

## Page and appendix structure

### Page 1: one-page verdict

Page 1 must remain exactly one page.

It contains four reading zones and one footer:

1. **Header strip**
2. **Hero verdict block**
3. **Signature proof block**
4. **Top actions block**
5. **Footer route guide**

### Zone 1 — Header strip

Required fields:

- run date/time
- car name/type
- duration
- sensor count
- speed window label

Only show these if they fit without crowding:

- sensor model
- firmware version

All other metadata moves to Appendix D.

### Zone 2 — Hero verdict block

This is the strongest visual element on page 1.

#### Required fields

- **Suspected source**
- **Inspect first**
- **Action status**
- **One evidence-based reason sentence**

#### Source/location contract

Page 1 uses these nouns consistently:

- **Suspected source** = system class, for example `Wheel / Tire`, `Driveline`, `Engine`
- **Inspect first** = location, for example `Front-Left`
- **Also consider** = secondary source, not a second location

Do **not** blur source and location into one label such as “front-left wheel/tire” in the main page-1 headline.

#### Required hero copy pattern

- `Suspected source: Wheel / Tire`
- `Inspect first: Front-Left`
- `Action status: Action-ready with caution`
- `Why this is first: wheel/tire remains the strongest source because the repeated pattern matched that source and was strongest near the front-left corner in the 100–110 km/h window.`

#### What is intentionally not in the hero block

- dB metrics
- full ambiguity explanation
- full secondary-candidate reasoning
- measurement labels

Those belong in the proof/evidence appendices.

`Action status` is the **only page-1 verdict state**. Any other page-1 label must read as supporting proof or supporting context, not as a second trust decision.

### Zone 3 — Signature proof block

This is the defining VibeSensor-specific module.

It combines:

- a large vehicle hotspot map
- one location-confidence support label
- one coverage label
- one optional `Also consider` source chip

This block exists to answer: **why this corner wins**.

#### Required elements

- vehicle map with all expected positions
- dominant-corner highlight
- missing positions visibly marked as missing
- one-line proof summary
- one-line caveat if localization is mixed or weak

#### Required copy pattern

- `Why this corner wins`
- `Dominant corner: Front-Left`
- `Location confidence: Mixed`
- `Coverage: 4 of 4 wheel positions seen throughout run`
- `Also consider: Driveline`

#### Metric contract for this block

The map and any adjacent location callout use **one topology metric only**.

Wave-1 requirement:

- use **p95 per-sensor intensity dB** for map emphasis and ladder values
- do not mix p95, mean, max, or diagnosis-strength dB inside the same topology surface

Important hierarchy rule:

- `Location confidence` is supporting proof text, not a second verdict state
- `Action status` remains the only page-1 action/trust state

### Zone 4 — Top actions block

Show **up to three evidence-backed actions**.

Each action row contains:

- action title
- short reason
- quick confirm signal

It must not contain:

- falsify text
- ETA
- freeform notes

If the prepared action plan only supports one or two credible actions, the report should show fewer rather than pad the list.

If `Action status = Recapture before acting`, the top actions switch to capture-improvement actions only. They must not present normal inspect/repair guidance on page 1.

### Footer route guide

The footer is not a content block. It is a directional cue.

Required pattern:

- `Need the inspection sequence? See A.`
- `Need the location proof? See B.`
- `Need the evidence rows? See C.`
- `Need run details? See D.`

## Appendix A — Technician Worksheet

### Purpose

Appendix A is the **workflow appendix**.

A technician should be able to use it without reverse-engineering the rest of the report.

### Required blocks

1. **Primary vs alternative source block**
2. **Ranked source stack**
3. **Action matrix**

### 1. Primary vs alternative source block

Required fields:

- primary source
- alternative source, if materially relevant
- why the primary source is first
- what to inspect next if the primary path is clean

Important limit:

- do not invent a bespoke “best separating test” unless the current action-planning logic provides a clear source-backed discriminator
- if such a discriminator does not exist, the report should say `If the primary inspection is clean, continue with the alternative path below` rather than fabricate certainty

### 2. Ranked source stack

Show up to three source candidates with:

- rank
- source name
- inspect-first location
- action status detail (`primary path`, `alternative path`, `low-confidence path`)
- short reason it remains in scope

### 3. Action matrix

Columns:

- action
- why
- confirm
- falsify

No ETA field in wave 1.

No workshop notes field in wave 1.

### Recapture-mode Appendix A variant

If `Action status = Recapture before acting`, Appendix A switches from a technician worksheet to a **Capture Guidance** variant.

That variant contains:

- what was insufficient in the current run
- what to change in the next capture
- what conditions are needed for a stronger result

It must not lead with normal inspect/repair actions in recapture mode.

## Appendix B — Sensor Topology

### Purpose

Appendix B is the **spatial proof appendix**.

It should feel like the most distinctly VibeSensor part of the report.

### Required blocks

1. **Detailed sensor map**
2. **Intensity ladder**
3. **Dominance summary**
4. **Coverage detail**

### Detailed sensor map

For each active sensor, show:

- location
- topology metric value (same metric everywhere in this appendix)
- partial or missing status if relevant

### Intensity ladder

Order positions strongest to weakest using the same topology metric as the map.

Example structure:

- `Front-Left — 35.7 dB p95`
- `Front-Right — 33.7 dB p95`
- `Rear-Left — 33.3 dB p95`
- `Rear-Right — 33.2 dB p95`

### Dominance summary

Required outputs:

- dominant corner
- next strongest corner
- dominance ratio
- location confidence label

### Coverage detail

Required outputs:

- expected positions vs observed positions
- partial coverage
- disconnected mid-run if available
- why coverage quality affects trust in the location call

## Appendix C — Evidence Detail

### Purpose

Appendix C is the **evidence appendix**.

It should be narrower than previous drafts. It does not own every leftover analytic detail.

### Required blocks

1. **Evidence-chain table**
2. **Supporting context block**
3. **Suitability detail**

### 1. Evidence-chain table

This table makes the verdict auditable.

Required columns:

- source candidate
- supporting signal label
- referenced measurement IDs
- matched evidence-window count
- speed window
- dominant location
- ambiguity note

Important change from earlier drafts:

- remove abstract columns like `confidence effect`
- require row references and matched counts so the chain can point at measurable evidence

#### Evidence-reference contract

- every measurement row in Appendix C gets a stable visible ID such as `M01`, `M02`, `M03`
- evidence-chain rows reference those IDs directly
- `matched evidence-window count` refers to the number of supporting persisted analysis windows/intervals, not raw accelerometer samples

### 2. Supporting context block

This block owns the following supporting material in one place:

- supporting measurements table
- speed-band summary
- phase summary
- additional observations / transient observations

This is intentionally one block rather than four separate mini-appendices.

#### Measurements table columns

- rank
- matched system (`unassigned` allowed if safe inference is unavailable)
- matched pattern label
- frequency / order label
- peak dB
- strength dB
- speed window
- interpretation

#### Metric contract for Appendix C

- diagnosis/evidence tables may use **peak dB** and **strength dB**
- speed-band summary uses the existing persisted speed-band metrics
- Appendix C must label each metric explicitly; it may not reuse topology metrics without relabeling them

### 3. Suitability detail

Appendix C contains the full run-quality checklist behind the page-1 action status.

Required items:

- speed variation
- sensor coverage
- reference completeness
- saturation and outliers
- frame integrity
- run duration

## Appendix D — Run Context

### Purpose

Appendix D is the **traceability appendix**.

It stays compact.

### Required fields

- run ID
- timestamps
- car metadata used in analysis
- tire/drivetrain assumptions used in analysis
- sensor model
- firmware version
- sample count
- raw sample rate
- export package reference

Implementation note:

- Appendix D may share the last physical page with Appendix C if layout needs it.
- It remains a named appendix even if it occupies only a small final section.

## Content hierarchy

### Level 1 — act now

- suspected source
- inspect first
- action status
- up to 3 actions

### Level 2 — why this corner wins

- hotspot map
- location confidence
- coverage
- alternative source if relevant

### Level 3 — technician workflow

- primary vs alternative
- ranked source stack
- action matrix

### Level 4 — audit trail

- evidence-chain table
- supporting context
- suitability detail
- metadata and assumptions

## States and variants

### Action-status contract

Page 1 uses only these three trust states:

- **Action-ready**
- **Action-ready with caution**
- **Recapture before acting**

These states must be derived before rendering.

The renderer should receive a stable enum, not infer the state from mixed fields.

### Wave-1 mapping rules

History/report preparation should map to the enum using these rules:

- **Recapture before acting** when any of the following is true:
  - no dominant source is available
  - certainty tier is low
  - localization confidence is weak
  - blocking suitability failures exist (coverage, frame integrity, or reference completeness)
- **Action-ready with caution** when a dominant source exists and blocking failures do not exist, but any of the following is true:
  - medium certainty
  - visible alternative source remains in scope
  - localization confidence is mixed
  - non-blocking suitability warnings exist, such as short run duration
- **Action-ready** when a dominant source exists, localization is not weak, and no blocking or caution-triggering conditions remain

### Location-confidence contract

Appendix B and page 1 both use the same location-confidence enum:

- **Strong**
- **Mixed**
- **Weak**

Wave-1 derivation rules:

- **Strong**: `weak_spatial_separation = false`, dominance ratio >= 1.75, and no missing primary-corner coverage
- **Mixed**: `weak_spatial_separation = false` and dominance ratio between 1.25 and 1.74, or partial coverage exists
- **Weak**: `weak_spatial_separation = true`, dominance ratio < 1.25, or the primary-corner coverage is materially incomplete

If code reality contradicts these provisional thresholds, preserve the enum and adjust the gates in history-side preparation rather than changing the PDF structure.

### Alternative-source trigger

`Also consider` appears only when all of the following are true:

- a second ranked source exists
- it is a different source class from the primary source
- it remains materially close to the primary source, or prepared report facts explicitly mark the verdict as ambiguous

Wave-1 default rule:

- treat “materially close” as an absolute confidence gap of `<= 0.20`

If code reality requires different gating, preserve the existence of a deterministic trigger and adjust the threshold in history-side preparation rather than in PDF layout code.

### Explicit recapture-mode copy

When `Action status = Recapture before acting`, page 1 should switch away from normal diagnostic phrasing.

Required pattern:

- `Current result is not strong enough to act on yet.`
- `Best current lead: Wheel / Tire` or `No clear dominant source yet`
- `Capture another run with longer steady-speed coverage and full sensor visibility.`

This avoids simultaneously sounding diagnostic and non-committal.

## Important copy patterns

### Required page-1 labels

- `Suspected source`
- `Inspect first`
- `Action status`
- `Why this is first`
- `Why this corner wins`
- `Also consider`

### Avoid on page 1

- `Observed signature`
- `confidence tier`
- `certainty effect`
- unexplained `order` terminology
- labels that merge source and location into one noun

### Appendix language

Appendices may use technical terms such as:

- wheel-order
- driveshaft-order
- matched frequency
- dominance ratio
- transient impact

But each term must be adjacent to enough structure that a technician can understand why it matters.

## Data visualizations and component rules

### Required components

- compact header strip
- hero verdict lockup
- action-status badge/treatment
- signature proof map module
- top-action list
- footer route guide
- ranked source stack
- action matrix
- detailed topology map
- intensity ladder
- evidence-chain table
- supporting context block
- suitability checklist
- metadata table

### Non-negotiable layout rules

- the hero verdict block must be visually larger than any metadata treatment
- the signature proof map must occupy more area than any single appendix-style table on page 1
- action rows must be explicitly numbered
- appendix letters A/B/C/D must appear in a consistent location on appendix pages

### Metric rules

- topology surfaces use **p95 per-sensor intensity dB** only
- evidence surfaces label **peak dB** and **strength dB** separately
- no page may show two differently derived dB values without explicit labels

## Implementation notes

This redesign requires a small set of new history-side prepared outputs. They must be derived in report preparation/facts code, not in renderer modules.

Wave-1 derived outputs:

- `action_status`
- `location_confidence`
- `alternative_source_label` when ambiguity is material
- `primary_reason_sentence`
- `evidence_chain_rows`
- `coverage_summary_label`
- `alternative_source_visible`
- `measurement_ref_ids`
- `matched_evidence_window_count`

The PDF renderer should consume these as prepared fields.

## What is intentionally removed from the old approach

- large page-1 metadata slab
- split trust language across multiple page-1 regions
- page-1 jargon that reads like analyst notes
- blank evidence labels
- overlapping appendix responsibilities
- ETA and workshop-notes features in wave 1
- broad retest-success logic that would turn this into a comparison workflow

## What is preserved from the chosen baseline design

- strict one-page summary
- appendices for depth
- hotspot map as a core report surface
- up to 3 page-1 actions
- visible ambiguity when needed
- PDF as the delivery format
- owner-facing summary plus technician/multi-sensor depth

## Edge cases

- **No dominant source:** page 1 switches to recapture-mode copy.
- **Single-sensor run:** topology appendix becomes a reduced coverage explanation rather than fake localization.
- **Ambiguous overlap:** page 1 shows `Also consider`, Appendix A shows the alternative path.
- **Short run but otherwise usable:** page 1 remains `Action-ready with caution`, not `Action-ready`.
- **One-speed-window run:** the speed window still appears, but as a label rather than a chart-heavy section.
- **Unknown metadata fields:** Appendix D shows them as unavailable without polluting page 1.

## Success criteria

The redesign is successful if:

1. A first-time user can understand page 1 in under 20 seconds.
2. Page 1 answers trust through one `Action status` treatment instead of several competing labels.
3. Appendix A gives a technician a credible workflow without fabricated certainty.
4. Appendix B makes the spatial case unmistakably stronger than the current report.
5. Appendix C can trace the verdict to evidence rows and matched counts.
6. The design can be implemented in the current report pipeline by adding prepared fields on the history side rather than teaching renderer modules to invent logic.

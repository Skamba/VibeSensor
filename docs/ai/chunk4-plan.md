# Chunk 4 Plan: Eliminate Redundant Data Transformations

## Mapped Findings

| ID | Original Finding | Source Subagents |
|----|-----------------|-----------------|
| A1/B1/D1/D3 | FindingPayload↔Finding round-trips: 4-5 crosses per run + unconditional on every history read | Architecture #1, Abstraction #1, Data Flow #1, Data Flow #3 |
| A3 | Phase segments four parallel representations | Architecture #3 |
| D2/B3 | Sub-concept parallel types + SuspectedVibrationOrigin TypedDict mirror | Data Flow #2, Abstraction #3 |

## Validation Summary

### A1/B1/D1/D3: FindingPayload↔Finding Round-Trips — CONFIRMED

Within one analysis run, findings undergo these transformations:
1. `PeakBin.to_finding()` → `FindingPayload` dict (construction)
2. `finalize_findings()` → `Finding` domain objects (payload→domain)
3. `build_findings_bundle()` → `finding_payload_from_domain()` (domain→payload for `build_phase_timeline`)
4. `RunAnalysis.summarize()` → `finding_payload_from_domain()` again (domain→payload for AnalysisSummary)

Step 3 is redundant: `build_phase_timeline()` accepts `list[FindingPayload]` and uses `.get("finding_id")`, `.get("confidence")`, `.get("phase_evidence")` — all fields directly available as attributes on domain `Finding`.

On every history read, `project_analysis_summary()` in `boundaries/diagnostic_case.py:90` does a full round-trip: payload → `test_run_from_summary()` → full domain `TestRun` reconstruction → `finding_payload_from_domain()` per finding → returns updated payload. Three of four call sites discard the `TestRun` with `projected, _ = project_analysis_summary(...)`.

Total `finding_payload_from_domain` call sites: 6 across the codebase.

### A3: Phase Segments Four Representations — CONFIRMED

Four types carry essentially the same 8 fields:
1. `PhaseSegment` (mutable dataclass, `phase_segmentation.py:38`)
2. `DrivingSegment` (frozen dataclass, `domain/driving_segment.py:39`)
3. `AnalysisWindow` (frozen dataclass, `analysis_window.py:25`)
4. `PhaseSegmentSummary` (TypedDict, `_types.py:211`)

`DrivingSegment` is actively used in `TestRun.driving_segments` but is constructed by direct field transcription from `PhaseSegment`. `AnalysisWindow` renames `start_t_s`→`start_time_s` and is used by analysis pipeline consumers via `PreparedRunData.analysis_windows`.

### D2/B3: Sub-Concept Parallel Types — CONFIRMED

Location: 3 types (`LocationAnalysisResult` → `LocationHotspotPayload` → `LocationHotspot`) with field-name mismatches between them (`top_location` vs `strongest_location`).

Evidence: `FindingEvidenceMetrics` (26-field TypedDict) vs `FindingEvidence` (10-field domain dataclass) — 16 fields silently dropped during conversion in `finding_evidence_from_metrics()`.

Origin: `SuspectedVibrationOrigin` (8-key TypedDict) mirrors `VibrationOrigin` (6-field dataclass) with field renames (`reason`→`explanation`, `hotspot`→expanded to `location` + `alternative_locations` + `weak_spatial_separation`).

## Simplification Strategy

### Step 1: Make build_phase_timeline Accept Domain Findings (A1/D1 — eliminate redundant step 3)

1. Change `build_phase_timeline()` signature from `findings: list[FindingPayload]` to `findings: Sequence[Finding]`
2. Replace dict `.get()` calls with attribute access:
   - `finding.get("finding_id")` → `finding.finding_id`
   - `finding.get("confidence")` → `finding.confidence`
   - `finding.get("phase_evidence")` → `finding.phase_evidence` (verify attribute name)
3. In `build_findings_bundle()`, remove the `finding_payloads = [finding_payload_from_domain(f) for f in domain_findings]` conversion
4. Pass `domain_findings` directly to `build_phase_timeline()`
5. This eliminates one full O(n_findings) serialization pass per analysis run

### Step 2: Make project_analysis_summary Conditional (D3 — eliminate per-read round-trip)

This is the highest-impact change but also highest-risk. Two approaches:

**Approach A (conservative — recommended):** Add a schema version marker to summaries written by current code. On read, skip projection if the marker is present:
1. In `summarize()`, add `summary["_schema_version"] = CURRENT_SCHEMA_VERSION` to the persisted AnalysisSummary
2. In `project_analysis_summary()`, check for the version marker. If current, return the raw summary and construct `TestRun` lazily only when the caller actually needs it
3. The 3 callers that discard the TestRun (`projected, _ = ...`) skip reconstruction entirely
4. The 1 caller that uses the TestRun (history/reports.py) still gets it constructed

**Approach B (deeper — deferred):** Persist domain objects and skip reconstruction entirely. This requires schema migration and is too risky for this chunk.

**Going with Approach A.** Implementation:
1. Add `_CURRENT_SUMMARY_VERSION = 2` constant
2. In `RunAnalysis.summarize()`, set `summary["_summary_version"] = _CURRENT_SUMMARY_VERSION`
3. In `project_analysis_summary()`:
   - If `analysis.get("_summary_version") == _CURRENT_SUMMARY_VERSION`, return `(analysis, None)` for callers that don't need TestRun
   - Provide a separate `project_analysis_summary_with_domain()` for the report caller
   - Or make `project_analysis_summary()` return the TestRun lazily
4. Update the 3 discard callers in `history/runs.py` and `history/exports.py`
5. Keep the full projection path for legacy summaries without the version marker

### Step 3: Collapse Phase Segment Representations (A3)

1. Remove `AnalysisWindow` dataclass — merge its role into `PhaseSegment`:
   - `PhaseSegment` already has all the fields `AnalysisWindow` needs
   - Rename access patterns in consumers to use `PhaseSegment` directly
   - `PreparedRunData.analysis_windows` becomes `PreparedRunData.phase_segments` (or access them from the same source)
2. Keep `DrivingSegment` for now — it's actively used in `TestRun.driving_segments` and its construction from `PhaseSegment` is straightforward. Removing it would require changing the domain model.
3. Keep `PhaseSegmentSummary` TypedDict as the JSON serialization shape (it's needed for persistence)
4. Unify the NaN-to-None coercion: move it into `PhaseSegment` construction so it happens once at creation time rather than being duplicated in `serialize_phase_segments()` and `build_domain_driving_segments()`

**Net result:** From 4 representations to 2+serializer (PhaseSegment as the canonical pipeline type, DrivingSegment as the domain type, PhaseSegmentSummary as the persistence shape with a single serializer function).

### Step 4: Simplify Evidence Type Surface (D2 partial)

1. The `FindingEvidenceMetrics` → `FindingEvidence` 26→10 field reduction is an intentional design decision (only 10 fields are needed downstream). The silent data loss is the concern — not the type split itself.
2. Add a comment documenting the intentional field reduction in `finding_evidence_from_metrics()`
3. If any of the dropped fields are actually useful (e.g., `p95_intensity_db`, `matched_samples`), promote them to `FindingEvidence`
4. The `LocationAnalysisResult` → `LocationHotspot` path has genuine complexity reduction (14→7 fields). Keep it but improve the field-name consistency (`top_location` vs `strongest_location` should use one name)

### Step 5: Document SuspectedVibrationOrigin Purpose (D2/B3)

The `SuspectedVibrationOrigin` TypedDict and `VibrationOrigin` domain class serve different roles:
- `VibrationOrigin` is the domain object with computed properties
- `SuspectedVibrationOrigin` is the persistence/payload shape with those properties pre-evaluated

This is the same pattern as `Finding`/`FindingPayload` and is structurally the same as the round-trip problem, but at a smaller scale. The translators (`origin_payload_from_finding`, `vibration_origin_from_payload`) are 60 lines of mechanical code.

**Conservative approach for this chunk:** Don't remove `SuspectedVibrationOrigin` — it serves the persistence boundary. Instead, reduce the translation code where possible. If Approach A from Step 2 succeeds and we skip projection for current summaries, the origin translation becomes a write-once-read-never pattern for current data.

## Simplification Crosswalk

### A1/B1/D1/D3: FindingPayload↔Finding Round-Trips
- **Validation result:** CONFIRMED — 6 call sites for finding_payload_from_domain, step 3 is pure waste
- **Root cause:** Pipeline functions never updated to accept domain objects; boundary projection runs on every read
- **Steps:** Steps 1 + 2
- **Areas:** `summary_builder.py` (`build_findings_bundle`, `build_phase_timeline`), `boundaries/diagnostic_case.py` (`project_analysis_summary`), `use_cases/history/runs.py`, `use_cases/history/exports.py`
- **Removed:** 1 redundant O(n) serialization pass per analysis run, per-read domain reconstruction for current-format summaries
- **Verification:** Analysis produces identical AnalysisSummary output, history reads return same payload shapes, PDF reports unchanged

### A3: Phase Segments Four Representations
- **Validation result:** CONFIRMED — 4 types for same concept, 2 translation functions with duplicated NaN handling
- **Root cause:** Types added incrementally as layers were introduced
- **Steps:** Step 3
- **Areas:** `analysis_window.py` (merge into PhaseSegment usage), `summary_builder.py` (unify NaN handling)
- **Removed:** `AnalysisWindow` type (or inline it), duplicate NaN-coercion code
- **Verification:** Phase segmentation produces same results, analysis windows used correctly by pipeline

### D2/B3: Sub-Concept Parallel Types
- **Validation result:** CONFIRMED — multiple parallel types for evidence, location, origin
- **Root cause:** Domain objects layered on top of pre-existing payload format
- **Steps:** Steps 4 + 5
- **Areas:** `_types.py` (FindingEvidenceMetrics), `boundaries/vibration_origin.py` (SuspectedVibrationOrigin), `domain/finding_evidence.py`, `use_cases/diagnostics/location_analysis.py`
- **Removed:** Scope intentionally limited — document the intentional field reduction, fix naming inconsistencies
- **Verification:** Evidence metrics compute correctly, origin payloads unchanged

## Dependencies

- **Depends on Chunk 1:** DiagnosticReasoning removal simplifies the `summarize()` function that this chunk modifies.
- **Depends on Chunk 3:** F2/F3 type registry cleanup may affect import paths for types used in this chunk's changes.
- **Independent of Chunk 2 and Chunk 5.**

## Risks and Tradeoffs

1. **Step 1 (build_phase_timeline):** Low risk — changing function signature from dict to dataclass is straightforward. Need to verify all attributes are available on `Finding` (finding_id, confidence, phase_evidence).

2. **Step 2 (conditional projection):** Medium risk — adding a schema version and skipping projection could mask normalization bugs in legacy data. Mitigation: keep full projection for pre-v2 summaries, only skip for known-good current format.

3. **Step 3 (AnalysisWindow removal):** Medium risk — consumers that build `AnalysisWindow` must be updated to use `PhaseSegment` directly. The time field rename (`start_t_s` vs `start_time_s`) needs to be handled.

4. **Steps 4-5 (parallel types):** Conservative scope — we're documenting and fixing names rather than removing types. The deeper simplification (removing `SuspectedVibrationOrigin` or `FindingEvidenceMetrics`) requires changing the persistence format, which is out of scope for this chunk.

## Required Documentation Updates
- Update `docs/analysis_pipeline.md` if it references the old data flow
- Update `docs/ai/repo-map.md` for any removed types

## Required AI Instruction Updates
- Add: "When adding domain objects, update pipeline functions to accept them directly instead of requiring round-trips through payload dicts."
- Add: "Do not create TypedDict representations of domain objects unless they serve a genuine persistence or API serialization boundary."

## Required Test Updates
- Update `build_phase_timeline` tests to pass domain `Finding` objects instead of dicts
- Update history read tests if projection behavior changes
- Add a test verifying that current-format summaries skip full reconstruction
- Update or remove `AnalysisWindow`-specific tests

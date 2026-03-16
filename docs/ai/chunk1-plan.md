# Chunk 1 Plan: Remove Phantom DDD Infrastructure + Merge Satellite Domain Modules

## Mapped Findings

| ID | Original Finding | Source Subagents |
|----|-----------------|-----------------|
| A2/B2 | DiagnosticReasoning chain is phantom DDD infrastructure | Architecture #2, Abstraction #2 |
| F1 | Domain satellite fragmentation: 22 files, 8+ single-consumer modules | Folder Structure #1 |

## Validation Summary

### Finding A2/B2: DiagnosticReasoning Phantom DDD Infrastructure

**Validation result: CONFIRMED — the entire chain is production-unused scaffolding.**

The diagnostic reasoning chain consists of 6 domain types and 3 service functions in `domain/diagnostic_reasoning.py` (334 lines) plus multi-run case management logic in `domain/diagnostic_case.py` (~280 lines). The chain runs in every call to `RunAnalysis.summarize()`:

1. `_build_observation_evidence(domain_findings)` → `list[ObservationEvidence]`
2. `extract_observations(evidence_items)` → `tuple[Observation, ...]`
3. `recognize_signatures(observations)` → `tuple[Signature, ...]`
4. `evaluate_hypotheses(signatures)` → `tuple[Hypothesis, ...]`
5. `DiagnosticReasoning(observations, signatures, hypotheses)` stored in `TestRun.reasoning`
6. `DiagnosticCase.start().add_run(test_run)` triggers `reconcile()`

**Production impact of this chain: ZERO.** The only field read downstream from the `DiagnosticCase` is `.case_id` (a UUID) at `post_analysis.py:256`. The `.hypotheses`, `.diagnoses`, `.recommended_actions`, `.evidence_gaps`, `.is_complete` fields produced by `reconcile()` are never read by any HTTP route, persistence adapter, report mapper, or export consumer.

**Key evidence:**
- `hypothesis_epistemic_rules()` on DiagnosticCase: ZERO production callers
- `reconcile()`: called only from `add_run()`, which is called only from `summary_builder.py:1152` and `boundaries/diagnostic_case.py:375` (reconstruction)
- `TestRun.reasoning.hypotheses/signatures/observations`: read only inside `diagnostic_case.py` itself (lines 150, 190)
- A divergent shortcut path already exists: `DiagnosticReasoning.from_findings()` in `boundaries/diagnostic_case.py:326` skips the observation/signature/hypothesis pipeline entirely
- `Diagnosis` type: created only by `reconcile()`, stored in `case.diagnoses`, never read externally
- `Symptom` type: constructed to pass to `DiagnosticCase.start()`, never serialized or read downstream

**Exception — Signature:** `Signature.from_label()` is called in `boundaries/finding.py:222` when deserializing `signatures_observed` from persisted findings. However, the `Signature` objects themselves are not what drives the reasoning chain — only their `.label` strings are used. The `Signature` dataclass can be retained as a thin type for the label list, or finding.signature_labels can use `list[str]` directly.

**Validated root cause:** The reasoning chain was built as forward infrastructure for a multi-run diagnostic case feature. That feature requires persistent case_id attachment to runs, which does not exist (explicit blocker at `boundaries/diagnostic_case.py:256`). Until that infrastructure exists, the chain produces complex intermediate artifacts that are computed, stored in transient objects, and immediately discarded.

### Finding F1: Domain Satellite Fragmentation

**Validation result: CONFIRMED — 8 modules are single-consumer or zero-consumer satellites.**

Direct inspection confirmed these merge candidates:

| Module | Lines | Primary Consumer | External Production Consumers | Merge Target | Confidence |
|--------|-------|------------------|-------------------------------|--------------|------------|
| `diagnosis.py` | 63 | `diagnostic_case.py` | 1 (diagnostic_case.py only) | `diagnostic_case.py` | Strong |
| `symptom.py` | 40 | `diagnostic_case.py` | 2 (boundaries/diagnostic_case + summary_builder) | `diagnostic_case.py` | Strong |
| `finding_evidence.py` | 63 | `finding.py` | 2 (finding.py TYPE_CHECKING + boundaries/finding.py) | `finding.py` | Strong |
| `measurement.py` | 133 | `run_capture.py` | 1 (run_capture.py); VibrationReading has 0 consumers | `run_capture.py` | Moderate |
| `report.py` | 44 | `adapters/pdf/mapping.py` | 1 (mapping.py only) | `adapters/pdf/mapping.py` | Strong |

Additionally, once the DiagnosticReasoning chain is removed (A2/B2), `diagnostic_reasoning.py` (334 lines) will be entirely deleted, and `diagnostic_case.py` will be significantly simplified, further reducing domain module count.

**Modules NOT candidates for merge (validated as well-connected):**
- `run_status.py` (56 lines, 3+ external consumers across persistence/history)
- `speed_source.py` (88 lines, 4 consumers spanning config/API/boundaries/capture)
- `confidence_assessment.py` (113 lines, 3 consumers; rich logic justifies standalone)
- `vibration_origin.py` (115 lines, has dedicated boundary adapter with its own scope)
- `location_hotspot.py` (200 lines, multiple consumers)

## Root Causes

1. **Forward-infrastructure addiction:** The DiagnosticReasoning chain was designed for a multi-run case management feature that requires infrastructure (persistent case attachment) that doesn't exist. The chain was wired into the critical analysis path preemptively.

2. **Uniform one-file-per-type rule:** The domain modeling guidelines mandated "each primary domain object lives in its own dedicated file" without distinguishing between richly-connected types (Finding, DiagnosticCase) and satellite types consumed by only 1-2 files.

## Simplification Strategy

### Phase 1: Remove the DiagnosticReasoning Chain

**Step 1: Remove the reasoning chain from `summarize()`**
- In `summary_builder.py`, remove `_build_observation_evidence()` function (~30 lines)
- Remove the 4-step chain at lines 1108-1111 (`extract_observations`, `recognize_signatures`, `evaluate_hypotheses`)
- Remove the `DiagnosticReasoning(...)` construction
- Remove `reasoning=reasoning` from `TestRun(...)` construction
- Remove `DiagnosticCase.start().add_run()` call and the diagnostic_case result field
- Keep the `case_id` generation — assign `case_id = str(uuid.uuid4())` directly where needed

**Step 2: Simplify TestRun**
- Remove `reasoning: DiagnosticReasoning` field from `domain/test_run.py`
- Remove any imports of `DiagnosticReasoning` from `test_run.py`

**Step 3: Simplify DiagnosticCase**
- Remove `reconcile()`, `add_run()`, `hypothesis_epistemic_rules()`, `classify_hypothesis_sequence()`, `classify_finding_sequence()` methods
- Remove `DiagnosticCaseEpistemicRule` enum
- Remove `hypotheses`, `diagnoses`, `recommended_actions`, `evidence_gaps`, `is_complete`, `has_usable_evidence` fields
- Keep: `case_id`, `car`, `symptoms`, `test_runs` (for boundary reconstruction)
- Simplify `start()` to just create a minimal case with a UUID

**Step 4: Delete `domain/diagnostic_reasoning.py`**
- Delete the entire 334-line file
- Remove: `Observation`, `ObservationEvidence`, `Signature`, `HypothesisStatus`, `Hypothesis`, `DiagnosticReasoning`, `extract_observations`, `recognize_signatures`, `evaluate_hypotheses`
- For `Signature`: check if `Finding.signature_labels` can use `list[str]` directly instead of `Signature` objects. If `boundaries/finding.py` uses `Signature.from_label()`, replace with plain string construction.

**Step 5: Delete `domain/diagnosis.py`**
- Delete the file (63 lines, sole consumer was `reconcile()`)

**Step 6: Simplify `boundaries/diagnostic_case.py`**
- Remove `DiagnosticReasoning.from_findings()` shortcut (no longer needed)
- Simplify `test_run_from_summary()` to not construct DiagnosticReasoning
- Simplify `diagnostic_case_from_summary()` to not call reconcile
- Remove the blocker comment about case_id attachment

**Step 7: Update `domain/__init__.py`**
- Remove exports: `DiagnosticReasoning`, `Observation`, `ObservationEvidence`, `Signature`, `HypothesisStatus`, `Hypothesis`, `Diagnosis`, `DiagnosticCaseEpistemicRule`
- Keep exports: `DiagnosticCase` (simplified), `TestRun` (simplified)

### Phase 2: Merge Satellite Domain Modules

**Step 8: Merge `finding_evidence.py` into `finding.py`**
- Move `FindingEvidence` dataclass (10 fields) into `finding.py`
- Update `domain/__init__.py` to export from `finding` instead of `finding_evidence`
- Update `boundaries/finding.py` import
- Delete `finding_evidence.py`

**Step 9: Merge `symptom.py` into `diagnostic_case.py`**
- Move `Symptom` dataclass (simple: description + classmethod) into `diagnostic_case.py`
- Update imports in `boundaries/diagnostic_case.py` and `summary_builder.py`
- Update `domain/__init__.py`
- Delete `symptom.py`

**Step 10: Merge `measurement.py` into `run_capture.py`**
- Move `Measurement` and `VibrationReading` into `run_capture.py`
- Update `domain/__init__.py`
- Delete `measurement.py`

**Step 11: Merge `report.py` into `adapters/pdf/mapping.py`**
- Move `Report` dataclass (44 lines, pure data bag) into `mapping.py`
- `Report` is constructed and consumed solely in `mapping.py`
- Update `domain/__init__.py` to remove `Report` export
- Delete `report.py`

### Phase 3: Update Tests, Docs, and AI Instructions

**Step 12: Update tests**
- Fix all test imports that reference deleted modules
- Remove tests that exclusively test deleted functionality (observation/signature/hypothesis chain tests)
- Keep tests that validate `TestRun` behavior, `DiagnosticCase` case_id generation, and finding processing
- Update domain model characterization tests

**Step 13: Update documentation**
- Update `docs/domain-model.md` to remove DiagnosticReasoning, Observation, Signature, Hypothesis, Diagnosis from the domain object graph
- Update `docs/ai/repo-map.md` to reflect simplified domain layout
- Update `.github/copilot-instructions.md` domain model section

**Step 14: Update AI instructions**
- Add to `.github/instructions/backend.instructions.md`: "Do not introduce forward-looking infrastructure types until their persistence and delivery requirements exist."
- Add to `.github/instructions/general.instructions.md`: "Do not create domain types that are only consumed by a single class within the same package. Merge single-consumer satellites into their host file."

## Simplification Crosswalk

### A2/B2: DiagnosticReasoning Phantom DDD Infrastructure
- **Validation result:** CONFIRMED
- **Validated root cause:** Forward infrastructure for unimplemented multi-run case management
- **Implementation steps:** Steps 1-7 (remove chain, simplify TestRun/DiagnosticCase, delete files)
- **Code areas to change:** `domain/diagnostic_reasoning.py` (delete), `domain/diagnostic_case.py` (simplify), `domain/diagnosis.py` (delete), `domain/test_run.py` (remove reasoning field), `summary_builder.py` (remove chain), `boundaries/diagnostic_case.py` (simplify reconstruction), `domain/__init__.py` (remove exports), `post_analysis.py` (generate case_id directly)
- **What can be removed:** ~600 lines of domain code (diagnostic_reasoning.py + diagnosis.py + DiagnosticCase methods), ~30 lines from summary_builder.py, ~50 lines from boundaries/diagnostic_case.py
- **Verification:** All existing tests pass after changes. No HTTP route, persistence, or report output changes. `case_id` still generated and stored.

### F1: Domain Satellite Fragmentation
- **Validation result:** CONFIRMED for 5 modules
- **Validated root cause:** Uniform one-file-per-type rule applied without consumer analysis
- **Implementation steps:** Steps 8-11 (merge finding_evidence, symptom, measurement, report)
- **Code areas to change:** `domain/finding_evidence.py` (merge into finding.py), `domain/symptom.py` (merge into diagnostic_case.py), `domain/measurement.py` (merge into run_capture.py), `domain/report.py` (merge into adapters/pdf/mapping.py), `domain/__init__.py` (update exports)
- **What can be removed:** 4 domain files (~240 lines of standalone modules), replaced by inline content in their consumer modules
- **Verification:** All imports update cleanly. `domain/__init__.py` exports remain the same symbols from new locations. Tests pass.

## Dependencies on Other Chunks

- **None outbound.** This chunk is foundational and should execute first.
- Chunk 4 benefits from this chunk: removing DiagnosticReasoning simplifies the `summarize()` flow that Chunk 4 further simplifies.
- Chunk 3 benefits: fewer domain types means less boundary adapter code to maintain.

## Risks and Tradeoffs

1. **Loss of multi-run case infrastructure:** If the multi-run diagnostic case feature is wanted in the future, the reasoning chain would need to be rebuilt. However, the current implementation has an explicit blocker (no persistent case_id) and the chain produces no observable output. Rebuilding when the persistence exists would be cleaner than maintaining phantom infrastructure.

2. **Signature type removal:** `Finding.signature_labels` currently stores `tuple[Signature, ...]`. Changing to `tuple[str, ...]` is semantically equivalent (Signature is just a label wrapper) but requires updating `boundaries/finding.py` deserialization and any tests that construct Signature objects.

3. **Import path changes from merges:** All consumers import from `vibesensor.domain` (the package `__init__.py`), not from individual files. As long as `__init__.py` re-exports are updated correctly, no external import breaks.

## Required Documentation Updates

- `docs/domain-model.md`: remove DiagnosticReasoning section, update domain object graph
- `docs/ai/repo-map.md`: remove diagnostic_reasoning.py, diagnosis.py, symptom.py, measurement.py, finding_evidence.py, report.py from domain listing; update domain file count
- `.github/copilot-instructions.md`: simplify domain model description

## Required AI Instruction Updates

- Add to backend.instructions.md: "Do not introduce forward-infrastructure domain types whose persistence and delivery dependencies don't exist yet."
- Add to general.instructions.md: "Merge single-consumer domain satellite types into their primary consumer file. Only create standalone domain files for types with 3+ distinct production consumers."

## Required Test Updates

- Delete or update tests for `extract_observations`, `recognize_signatures`, `evaluate_hypotheses`
- Delete tests for `hypothesis_epistemic_rules`, `reconcile`, `classify_hypothesis_sequence`, `classify_finding_sequence`
- Update `TestRun` construction in tests to not pass `reasoning=`
- Update `DiagnosticCase` tests to reflect simplified structure
- Update import paths for merged types

## Validation Steps

1. All existing tests pass (except those testing removed functionality, which should be deleted)
2. `make lint` passes
3. `make typecheck-backend` passes
4. `pytest -q apps/server/tests/domain/` passes
5. `pytest -q apps/server/tests/use_cases/diagnostics/` passes
6. `pytest -q apps/server/tests/shared/boundaries/` passes
7. `pytest -q apps/server/tests/integration/` passes
8. The analysis pipeline still produces the same `AnalysisSummary` output (minus unused reasoning fields)
9. `case_id` still appears in stored summaries

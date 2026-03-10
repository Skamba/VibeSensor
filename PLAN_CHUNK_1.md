# Chunk 1: Dead Code, Unused Data & Payload Trimming

## Mapped Findings

| ID | Original Finding | Source Subagent | Validation Status |
|----|-----------------|-----------------|-------------------|
| D1 | Per-axis peak blobs stored but never read | Persistence & Schema | **Validated** |
| E1 | ClientApiRow embeds 16 unused diagnostic fields in every WS tick | API & Interface | **Validated** |
| E2 | Per-axis spectra (x/y/z) serialized in WS but discarded by frontend | API & Interface | **Validated** |
| E3 | SelectedClientPayload/WaveformPayload/build_selected_payload() dead pipeline | API & Interface | **Validated** |
| D3 | RunMetadata embeds three always-default documentation blobs | Persistence & Schema | **Validated** |
| C2 | ClientBuffer 4 generation counters + 2 payload caches | Data Flow & State | **Partially solved by E3** |

## Validation Outcomes

### D1: Per-axis peak blobs — VALIDATED
`top_peaks_x`, `top_peaks_y`, `top_peaks_z` columns in `_schema.py` SCHEMA_SQL. `_V2_PEAK_COLS` in `_samples.py`. `SensorFrame` carries them. Zero consumers in analysis/, report/, or UI. Only `top_peaks` (combined) is read by `_sample_top_peaks()`.

### E1: ClientApiRow WS bloat — VALIDATED
`ClientApiRow` has 23 fields. Frontend `parseClient()` uses only 10. The rest are serialized every WS tick for zero benefit.

### E2: Per-axis spectra — VALIDATED
`SpectrumSeriesPayload` has `x, y, z` fields. `build_spectrum_payload()` computes all three. Frontend `parseSpectra()` only reads `combined_spectrum_amp_g` and `strength_metrics`.

### E3: SelectedClientPayload dead pipeline — VALIDATED
`SelectedClientPayload`, `WaveformPayload`, `SelectedSpectrumPayload` TypedDicts, `build_selected_payload()` (~90 lines), `cached_selected_payload` / `cached_selected_payload_key` on `ClientBuffer`, `SignalProcessor.selected_payload()`. Zero production callsites.

### D3: RunMetadata always-default blobs — VALIDATED
`_default_units()`, `_default_amplitude_definitions()`, `_default_phase_metadata()` return fixed dicts. No code reads them.

### C2: ClientBuffer generation counters — REFINED
After E3 removal, `cached_selected_payload` and `cached_selected_payload_key` disappear. Remaining cache fields are justified. No further action needed beyond E3 cleanup.

## Root Causes

Speculative feature code: data structures built for undelivered features (per-axis spectrum display, per-sensor waveform view, per-axis peak analysis) are maintained but never consumed.

## Implementation Steps

### Step 1: Remove SelectedClientPayload dead pipeline (E3)
1. Delete `WaveformPayload`, `SelectedSpectrumPayload`, `SelectedClientPayload` from `payload_types.py`
2. Delete `build_selected_payload()` from `processing/payload.py` (~90 lines)
3. Remove imports of deleted types from `processing/payload.py`
4. Remove `cached_selected_payload` and `cached_selected_payload_key` from `ClientBuffer` in `processing/buffers.py`
5. Update `invalidate_caches()` to remove selected-payload cache clearing
6. Remove `selected_payload()` from `processing/views.py` and `processing/processor.py`
7. Clean up any test references

### Step 2: Remove per-axis spectra from WS payload (E2)
1. Remove `x`, `y`, `z` keys from `SpectrumSeriesPayload` in `payload_types.py`
2. Update `build_spectrum_payload()` to stop computing x/y/z
3. Update `EMPTY_SPECTRUM_PAYLOAD` and `_empty_spectrum_payload()` to remove x/y/z
4. Update WS payload schema JSON if needed

### Step 3: Trim ClientApiRow for WS broadcast (E1)
1. Create `ClientWsBriefRow` TypedDict with only the 10 frontend-consumed fields
2. Keep `ClientApiRow` for REST debug endpoint
3. Update WS broadcast builder to use brief row
4. Update WS payload schema JSON

### Step 4: Remove per-axis peak blobs (D1)
1. Remove `top_peaks_x`, `top_peaks_y`, `top_peaks_z` from SCHEMA_SQL
2. Bump SCHEMA_VERSION from 5 to 6
3. Remove per-axis peak entries from `_samples.py`
4. Remove per-axis peak fields from `SensorFrame` in `domain_models.py`
5. Remove per-axis peak extraction from `sample_builder.py`
6. Remove per-axis peak columns from CSV export
7. Update tests

### Step 5: Remove RunMetadata documentation blobs (D3)
1. Remove `units`, `amplitude_definitions`, `phase_metadata` from `RunMetadata`
2. Remove `_default_units()`, `_default_amplitude_definitions()`, `_default_phase_metadata()`
3. Remove parsing helpers used only for these fields
4. Update `create()`, `from_dict()`, `to_dict()`
5. If JSONL export needs unit docs, inject at export time only

### Step 6: Verify and update tests
1. Run targeted tests for processing, metrics_log, domain, history_db
2. Fix assertions on removed fields
3. Remove dead test code for selected-payload and axis peaks

## Dependencies on Other Chunks
None — pure removal, executes first.

## Risks and Tradeoffs
- Schema v5→v6 bump: existing DBs become incompatible (acceptable fail-fast behavior)
- JSONL export format changes: keep unit constants as export-time injection if needed
- REST API `GET /api/clients` keeps full diagnostic type for debugging

## Validation Steps
- `pytest -q apps/server/tests/processing/ apps/server/tests/metrics_log/ apps/server/tests/domain/ apps/server/tests/history_db/`
- `ruff check apps/server/`
- `make typecheck-backend`
- Frontend `npm run build` and `npm run typecheck`

## Simplification Crosswalk

| Finding | Steps | Removable | Verification |
|---------|-------|-----------|-------------|
| D1 | Step 4 | 3 schema cols, peak fields, extraction code, CSV cols | tests pass, no axis-peak references |
| E1 | Step 3 | 13 fields from WS broadcast | frontend renders, WS payload smaller |
| E2 | Step 2 | x/y/z from SpectrumSeriesPayload | parseSpectra works, no x/y/z in UI |
| E3 | Step 1 | ~100 lines dead code, 3 TypedDicts, 2 buffer fields, 2 methods | zero callsites for selected_payload |
| D3 | Step 5 | 3 fields, 3 defaults, 2 parsing helpers | RunMetadata smaller, tests pass |
| C2 | By Step 1 | 2 buffer cache fields | buffer has fewer fields |

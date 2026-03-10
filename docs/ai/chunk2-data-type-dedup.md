# Chunk 2: Data Type & Payload Deduplication

## Mapped Findings

| ID | Title | Validation | Status |
|----|-------|------------|--------|
| C1 | combined_spectrum_amp_g transmitted twice in heavy WS tick | VALID | Plan below |
| C2 | VibrationStrengthMetrics / StrengthMetricsPayload duplicate types | VALID | Plan below |
| C3 | MetricsPayload opaque heterogeneous dict | VALID | Plan below |
| I2 | vibesensor.core vestigial standalone package | VALID | Plan below |

## Root Causes

The data type layer evolved incrementally: `VibrationStrengthMetrics` was the original computation
output type in the `core` module; `StrengthMetricsPayload` was later added as a `total=False`
mirror for the buffer/WS layer. The `combined_spectrum_amp_g` array ended up in both the top-level
spectrum payload and inside `strength_metrics`, creating per-tick bandwidth waste. `MetricsPayload`
was designed as a flexible bag-of-metrics dict using string keys for axis discrimination, which
makes it un-narrowable in both Python and TypeScript type checkers. The `core/` sub-package
retains infrastructure from when it was a standalone pip package (`py.typed`, 24-symbol re-exports)
despite having zero external consumers.

## Validation Details

### C1: combined_spectrum_amp_g Transmitted Twice (VALID)

**Confirmed:** `VibrationStrengthMetrics.combined_spectrum_amp_g` (list[float]) is a required field.
`SpectrumSeriesPayload` has both `combined_spectrum_amp_g` at top level AND `strength_metrics`
(which is `StrengthMetricsPayload` containing the same field). Both are populated from the same
underlying numpy array in `processing/fft.py`.

**Plan:** Remove `combined_spectrum_amp_g` from `VibrationStrengthMetrics`. It belongs only in
`SpectrumSeriesPayload` as the spectrum channel the chart reads. `strength_metrics` should be
scalar-only: `vibration_strength_db`, `peak_amp_g`, `noise_floor_amp_g`, `strength_bucket`, `top_peaks`.

### C2: Duplicate Types with Identity Cast (VALID)

**Confirmed:** `VibrationStrengthMetrics` (6 required fields) and `StrengthMetricsPayload`
(6 optional fields via `total=False`) are structurally identical. A `cast("StrengthMetricsPayload", ...)`
bridges them in buffer_store.py. `_empty_strength_metrics()` in buffers.py also casts `{}` to
`StrengthMetricsPayload`.

**Plan:** After removing `combined_spectrum_amp_g` from `VibrationStrengthMetrics` (C1), use
`VibrationStrengthMetrics` directly everywhere. Delete `StrengthMetricsPayload`. The empty state
uses `empty_vibration_strength_metrics()` from the core module. Remove both casts and
`_empty_strength_metrics()`.

### C3: MetricsPayload Opaque Dict (VALID)

**Confirmed:** `MetricsPayload = dict[str, MetricEntry]` where `MetricEntry = AxisMetrics |
CombinedMetrics | VibrationStrengthMetrics`. String keys act as type discriminators. The
`strength_metrics` object appears at both `metrics["combined"]["strength_metrics"]` and
`metrics["strength_metrics"]` (same reference, stored in two places in compute.py).

**Plan:** Replace `MetricsPayload` with a concrete TypedDict:
```python
class ClientMetrics(TypedDict, total=False):
    x: AxisMetrics
    y: AxisMetrics
    z: AxisMetrics
    combined: CombinedMetrics
```
Remove the redundant top-level `strength_metrics` key from the metrics dict. Consumers access
`metrics["combined"]["strength_metrics"]` or better yet, `strength_metrics` is served only in
`SpectrumSeriesPayload` (via C1 resolution), not in per-tick metrics at all.

### I2: vibesensor.core Vestigial Package (VALID)

**Confirmed:** `vibesensor/core/` has 3 source files, a `py.typed` marker, and a 24-symbol
re-export `__init__.py`. ~30 import sites use `from vibesensor.core.vibration_strength import ...`
or `from vibesensor.core.strength_bands import ...`. No external consumers exist.

**Plan:** Remove the re-export `__init__.py` facade and `py.typed` marker. Keep the 3 source files
in place (moving them would create a very large import-rewriting exercise for little benefit).
The `core/` directory stays but becomes a normal internal package without the standalone-library
pretension. Update the docstring in `vibration_strength.py` to remove the "can be imported in
firmware simulators" claim.

## Implementation Steps

### Step 1: Remove combined_spectrum_amp_g from VibrationStrengthMetrics (C1)
1. Edit `core/vibration_strength.py`: remove `combined_spectrum_amp_g` from `VibrationStrengthMetrics`
2. Edit `core/vibration_strength.py`: remove from `empty_vibration_strength_metrics()`
3. Edit `processing/fft.py`: don't include `combined_spectrum_amp_g` in the strength_metrics result
4. Verify `processing/payload.py`: `build_spectrum_payload` still sets `combined_spectrum_amp_g` at
   top level of `SpectrumSeriesPayload` from the spectrum data (not from strength_metrics)
5. Update frontend `ws_payload_types.ts` if needed
6. Update any test assertions that check for `combined_spectrum_amp_g` in strength_metrics

### Step 2: Unify VibrationStrengthMetrics / StrengthMetricsPayload (C2)
1. Delete `StrengthMetricsPayload` from `payload_types.py`
2. Replace all imports of `StrengthMetricsPayload` with `VibrationStrengthMetrics`
3. In `buffers.py`: replace `_empty_strength_metrics()` with `empty_vibration_strength_metrics()`
4. In `buffer_store.py`: remove the `cast("StrengthMetricsPayload", ...)` call
5. In `SpectrumSeriesPayload`: change `strength_metrics: StrengthMetricsPayload` →
   `strength_metrics: VibrationStrengthMetrics`
6. Update TypeScript WS types if the schema changes

### Step 3: Replace MetricsPayload with typed ClientMetrics (C3)
1. Define `ClientMetrics(TypedDict, total=False)` with explicit x, y, z, combined fields
2. Remove the redundant `metrics["strength_metrics"]` assignment in `compute.py`
3. Replace `MetricsPayload` alias and `MetricEntry` union with `ClientMetrics`
4. Update `processing/models.py` to use `ClientMetrics`
5. Update `ClientApiRow.latest_metrics` type from `MetricsPayload` to `ClientMetrics`
6. Update all consumers that access `metrics["x"]`, `metrics["combined"]` (should work unchanged)
7. Remove any code that accesses `metrics["strength_metrics"]` (redundant with C1 spectrum data)
8. Update frontend WS payload types

### Step 4: Simplify vibesensor.core package (I2)
1. Remove `vibesensor/core/py.typed` marker
2. Replace `__init__.py` 24-symbol re-export facade with a simple `"""vibesensor.core — internal
   domain logic."""` docstring (or empty)
3. Update `vibration_strength.py` docstring to remove standalone-library claims
4. Verify all ~30 import sites still work (they import from specific submodules, not from
   `vibesensor.core` directly — need to verify this)

### Step 5: Update frontend WebSocket types
1. Update `apps/ui/src/contracts/ws_payload_types.ts`:
   - Remove `combined_spectrum_amp_g` from `StrengthMetricsPayload`/`VibrationStrengthMetrics`
   - Replace `latest_metrics` dict type with typed object
2. Update `apps/ui/src/server_payload.ts` if parsing logic changes

### Step 6: Update tests
1. Fix any test assertions checking `strength_metrics.combined_spectrum_amp_g`
2. Fix tests using `StrengthMetricsPayload`
3. Fix tests accessing `metrics["strength_metrics"]` at top level

## Dependencies on Other Chunks
- Must come AFTER Chunk 1 (which touches RuntimePersistenceSubsystem fields)
- No dependency FROM other chunks

## Risks
- WS payload format change is a breaking change (allowed by repo policy)
- Frontend must be updated to match backend type changes
- Processing hot path changes need careful testing
- `combined_spectrum_amp_g` removal from strength_metrics changes the analysis pipeline if any
  analysis code reads it from there (need to verify)

## Documentation Updates Required
- `docs/ai/repo-map.md`: update vibesensor.core description

## Validation
- `pytest apps/server/tests/processing/` for processing pipeline
- `pytest apps/server/tests/analysis/` for analysis pipeline
- Full `make test-all`
- `make typecheck-backend`
- `cd apps/ui && npm run typecheck && npm run build`

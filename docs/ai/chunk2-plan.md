# Chunk 2 Plan: Simplify Runtime, Configuration, and Operational Code

## Mapped Findings

| ID | Original Finding | Source Subagents |
|----|-----------------|-----------------|
| C1 | Two parallel in-memory settings stores (AnalysisSettingsStore + SettingsStore) | Config #1 |
| C2 | Shell hotspot script embeds duplicate config loader for ap section | Config #2 |
| C3 | UDP port constants flow through four representations | Config #3 |
| I2 | ClientApiRow/WsClientRow split forces duplicated registry snapshot logic | API #2 |
| I3 | Three parallel error-translation context managers | API #3 |
| L1 | vibration_strength.py dependency-free API forces numpy↔list round-trips | Dep #1 |
| L2 | Scattered duplicated statistics primitives | Dep #2 |

## Validation Summary

### C1: Two Parallel Settings Stores — CONFIRMED

`AnalysisSettingsStore` (220 lines in `infra/config/analysis_settings.py`) is a write-through cache of `SettingsStore`'s active car aspects. `_sync_analysis_settings()` is called at 6 sites in `settings_store.py` after every car mutation. The store has 6 readers (ws_broadcast, HTTP settings route, RunRecorder). The sync obligation is a maintenance trap — every future car mutation method must remember to call it.

**Root cause:** Separation was introduced so `WsBroadcastService` could be injected with a narrow read-only interface without depending on persistence/DB concerns.

**Key nuance:** `AnalysisSettingsStore` also contains validation logic (`sanitize_settings()`), geometry helpers (`tire_circumference_m_from_spec()`, `wheel_hz_from_speed_kmh/mps()`, `engine_rpm_from_wheel_hz()`), and `DEFAULT_ANALYSIS_SETTINGS`. These utility functions and constants are genuine shared logic, not just cache state. The merge must preserve this logic.

### C2: Shell Hotspot Script Duplicate Config — CONFIRMED (modest)

The shell heredoc in `hotspot_nmcli.sh:123` implements a bespoke shallow-merge for the `ap` section, bypassing `load_config()` validation. The companion `self_heal.py` properly calls `load_config()`.

**Scope refinement:** The fix is modest — add a thin CLI entry point that prints shell variable exports, replacing the heredoc. This is low-leverage but straightforward.

### C3: UDP Port Constants Four Representations — CONFIRMED

Port value 9000 traverses: `NETWORK_PORTS` dict → `DEFAULT_UDP_DATA_PORT` int → `"0.0.0.0:9000"` string in DEFAULT_CONFIG → `_split_host_port()` back to int in `UDPConfig`. A consistency-guard test (`test_network_ports_single_source_of_truth`) exists to verify the chain stays consistent.

**Key nuance:** The host:port string format exists because `DEFAULT_CONFIG` is YAML-compatible and users can override bind addresses. Removing the string form would require changing the YAML config schema.

**Scope refinement:** Simpler fix — remove `NETWORK_PORTS` dict and `DEFAULT_UDP_DATA_PORT`/`DEFAULT_UDP_CONTROL_PORT` intermediaries. Put `data_port: 9000` and `control_port: 9001` directly in `DEFAULT_CONFIG["udp"]` as integer keys alongside the host. Remove `_split_host_port()` and the consistency-guard test.

### I2: ClientApiRow/WsClientRow Split — CONFIRMED

`ClientApiRow` (14 fields) and `WsClientRow` (10 fields, strict subset) cause two ~40-line near-identical iteration methods in `registry.py`. The staleness logic is duplicated verbatim. The disconnected-client branch is handled differently (helper function vs inline dict).

### I3: Three Error-Translation Context Managers — CONFIRMED (partial)

`_value_error_to_http` (settings.py:38) and `_update_errors_to_http` (updates.py:33) both catch `ValueError→400`. The only difference: updates also catches `RuntimeError→409`. These are local duplicates that should be consolidated into the shared `domain_errors_to_http` or a sibling in `_helpers.py`.

### L1: vibration_strength.py Dependency-Free API — CONFIRMED

Module explicitly states "intentionally dependency-free (stdlib only)." All array functions accept `list[float]`. `fft.py` has `float_list()` helper used at 3+ call sites to convert numpy arrays. `combined_spectrum_amp_g()` implements `sqrt(mean(x²))` as nested Python loops instead of vectorized numpy.

**Scope refinement:** The dependency-free design was for a MicroPython firmware target that never materialized. The ESP32 firmware is C++. The simulator already imports numpy. However, the scalar functions (`vibration_strength_db_scalar`, `bucket_for_strength`) have no numpy need. Best approach: keep scalar functions pure-Python, promote array operations to accept numpy arrays (or `Sequence[float]`).

### L2: Scattered Statistics Primitives — CONFIRMED

Three `median` implementations: custom in `vibration_strength.py:81`, `statistics.median` in `summary_builder.py:11`, `np.nanmedian` in `fft.py:58`. Two `percentile` implementations: custom in `vibration_strength.py:93`, `_weighted_percentile` in `helpers.py:471`. Plus a wrapper `_weighted_percentile_speed` in `location_analysis.py:52`.

## Simplification Strategy

### Step 1: Merge AnalysisSettingsStore into SettingsStore (C1)

1. Move `DEFAULT_ANALYSIS_SETTINGS`, `sanitize_settings()`, and the geometry helpers (`tire_circumference_m_from_spec`, `wheel_hz_from_speed_kmh`, `wheel_hz_from_speed_mps`, `engine_rpm_from_wheel_hz`) from `analysis_settings.py` to a section within `settings_store.py` (or keep them as module-level functions in `settings_store.py`)
2. Add `analysis_settings_snapshot() -> dict[str, float]` method to `SettingsStore` — acquires its existing lock, reads active car aspects, sanitizes, returns flat dict
3. Remove `AnalysisSettingsStore` class entirely
4. In `container.py`, remove the separate `AnalysisSettingsStore()` construction; `RuntimeState` and all consumers receive `SettingsStore` directly
5. Update all 6 readers of `AnalysisSettingsStore.snapshot()` to call `settings_store.analysis_settings_snapshot()`:
   - `ws_broadcast.py:99`
   - `settings.py:172`, `settings.py:180`
   - `run/logger.py:225`, `run/logger.py:678`, `run/logger.py:707`
6. Remove all 6 `_sync_analysis_settings()` call sites from `SettingsStore`
7. Delete `analysis_settings.py`
8. Remove the hygiene test that guards `analysis_settings.py` import isolation

### Step 2: Simplify UDP Port Constants (C3)

1. In `settings.py`, replace `NETWORK_PORTS` dict with direct inline values in `DEFAULT_CONFIG`:
   ```python
   DEFAULT_CONFIG["udp"] = {
       "data_host": "0.0.0.0",
       "data_port": 9000,
       "control_host": "0.0.0.0",
       "control_port": 9001,
   }
   ```
2. Remove `DEFAULT_UDP_DATA_PORT` and `DEFAULT_UDP_CONTROL_PORT` module constants
3. Remove `_split_host_port()` function
4. Update `_load_udp_config()` to read host/port as separate keys instead of parsing a combined string
5. Update `sim_sender.py` to use `9000` inline as default port (remove `NETWORK_PORTS` import)
6. Delete the `test_network_ports_single_source_of_truth` test
7. Update config YAML files if they use the `data_listen` format (change to `data_host` + `data_port`)

### Step 3: Merge ClientApiRow/WsClientRow (I2)

1. In `payload_types.py`, make `latest_metrics` and the 3 other API-only fields optional in `ClientApiRow` (using `total=False` or `NotRequired`)
2. Delete `WsClientRow` TypedDict
3. In `registry.py`, delete `ws_snapshot()` method
4. Update `snapshot_for_api()` to accept an optional `include_metrics=True` flag
5. WebSocket broadcast path calls `snapshot_for_api(include_metrics=False)` — the result omits `latest_metrics`, `frame_samples`, `reset_count`, `last_reset_time`
6. Update all WebSocket broadcast callers to use `snapshot_for_api(include_metrics=False)`

### Step 4: Consolidate Error Context Managers (I3)

1. Extend `domain_errors_to_http` in `_helpers.py` to accept optional `catch_value_error: int | None = None` and `catch_runtime_error: int | None = None` parameters
2. When `catch_value_error` is set, catch `ValueError` and raise HTTPException with that status code
3. When `catch_runtime_error` is set, catch `RuntimeError` and raise HTTPException with that status code
4. Delete `_value_error_to_http` from `settings.py`
5. Delete `_update_errors_to_http` from `updates.py`
6. Update call sites to use `domain_errors_to_http(catch_value_error=400)` etc.

### Step 5: Accept numpy arrays in vibration_strength.py hot-path functions (L1)

1. Change `combined_spectrum_amp_g()` to accept `Sequence[Sequence[float]] | np.ndarray` and use numpy internally: `np.sqrt(np.mean(np.array(axis_spectra_amp_g)**2, axis=0))`
2. Change `compute_vibration_strength_db()` to accept `Sequence[float] | np.ndarray` for both `freq_hz` and `combined_spectrum_amp_g_values`
3. Change `noise_floor_amp_p20_g()` to accept arrays
4. Keep `vibration_strength_db_scalar()`, `bucket_for_strength()`, and `BANDS` as pure Python (scalar operations)
5. Remove `float_list()` from `fft.py` and all conversion call sites
6. Update the module docstring to note which functions accept numpy arrays
7. Keep `percentile()` and `median()` as pure Python (they're also used by the array functions internally) — OR replace them with numpy equivalents inside the array functions

### Step 6: Consolidate Statistics Primitives (L2)

1. Remove `median()` from `vibration_strength.py` — it reimplements `statistics.median`
2. In `vibration_strength.py` internal callers of `median()`, switch to `statistics.median`
3. Remove `percentile()` from `vibration_strength.py` — its callers (`findings.py`, `helpers.py`, `plots.py`) should use `numpy.quantile()` instead
4. Remove `_weighted_percentile_speed()` wrapper from `location_analysis.py:52` — callers should call `_weighted_percentile()` from `helpers.py` directly
5. Keep `_weighted_percentile()` in `helpers.py` as the single weighted variant (it's a genuinely different algorithm)

### Step 7: Add Hotspot Config CLI Entry Point (C2)

1. Add a `vibesensor-hotspot-config` CLI entry point that calls `load_config()` and prints shell variable exports for the `ap` section
2. In `hotspot_nmcli.sh`, replace the Python heredoc with a call to `vibesensor-hotspot-config`
3. Register the entry point in `pyproject.toml`

## Simplification Crosswalk

### C1: Two Parallel Settings Stores
- **Validation result:** CONFIRMED
- **Root cause:** Narrow read interface for WS broadcast separated from full SettingsStore
- **Steps:** Step 1 (merge AnalysisSettingsStore)
- **Areas:** `infra/config/analysis_settings.py` (delete), `infra/config/settings_store.py` (add method), `app/container.py`, `infra/runtime/ws_broadcast.py`, `adapters/http/settings.py`, `use_cases/run/logger.py`
- **Removed:** 1 class, 1 module, 6 sync call sites, 1 hygiene test
- **Verification:** All settings read/write tests pass, WS broadcast still receives correct analysis settings

### C2: Shell Hotspot Script Duplicate Config
- **Validation result:** CONFIRMED (modest scope)
- **Root cause:** Shell can't call Python load_config() directly
- **Steps:** Step 7 (add CLI entry point)
- **Areas:** `scripts/hotspot_nmcli.sh`, `pyproject.toml` (entry point), new CLI function in adapters/hotspot or cli
- **Removed:** ~15-line Python heredoc from shell script
- **Verification:** `hotspot_nmcli.sh` sources config correctly via CLI

### C3: UDP Port Constants
- **Validation result:** CONFIRMED
- **Root cause:** NETWORK_PORTS dict → intermediary constants → host:port string → parse chain
- **Steps:** Step 2 (inline port values)
- **Areas:** `app/settings.py`, `adapters/simulator/sim_sender.py`, YAML config files, consistency test
- **Removed:** `NETWORK_PORTS` dict, 2 module constants, `_split_host_port()` function, 1 test
- **Verification:** Server binds correct ports, simulator uses correct defaults

### I2: ClientApiRow/WsClientRow Split
- **Validation result:** CONFIRMED
- **Root cause:** Optimization to avoid sending metrics over WS
- **Steps:** Step 3 (merge types, delete ws_snapshot)
- **Areas:** `shared/types/payload_types.py`, `infra/runtime/registry.py`
- **Removed:** 1 TypedDict, 1 iteration method (~50 lines)
- **Verification:** WS broadcast and API snapshots both work correctly

### I3: Three Error Context Managers
- **Validation result:** CONFIRMED (partial duplication)
- **Root cause:** Service layers raise raw ValueError/RuntimeError instead of typed exceptions
- **Steps:** Step 4 (extend shared handler)
- **Areas:** `adapters/http/_helpers.py`, `adapters/http/settings.py`, `adapters/http/updates.py`
- **Removed:** 2 private context managers
- **Verification:** All HTTP error codes still correct, route tests pass

### L1: vibration_strength.py numpy round-trips
- **Validation result:** CONFIRMED
- **Root cause:** Dependency-free policy for non-existent MicroPython target
- **Steps:** Step 5 (accept numpy arrays in array functions)
- **Areas:** `vibration_strength.py`, `infra/processing/fft.py`
- **Removed:** `float_list()` helper, 3+ conversion call sites
- **Verification:** FFT pipeline produces identical results, strength calculations match

### L2: Scattered Statistics Primitives
- **Validation result:** CONFIRMED
- **Root cause:** Each implementation added locally at point of need
- **Steps:** Step 6 (consolidate to stdlib/numpy)
- **Areas:** `vibration_strength.py`, `use_cases/diagnostics/helpers.py`, `use_cases/diagnostics/location_analysis.py`
- **Removed:** Custom `median()`, custom `percentile()`, `_weighted_percentile_speed()` wrapper
- **Verification:** All statistical calculations produce identical results

## Dependencies

- **No dependencies on Chunk 1.** This chunk is independently executable.
- **Chunk 3 benefits:** L1 simplification (accepting numpy in vibration_strength) may affect how persistence tests construct sample data.
- **Chunk 5 depends:** Test entry point simplification (W3) references Makefile targets that this chunk doesn't change.

## Risks and Tradeoffs

1. **C1 (settings merge):** WsBroadcastService will now depend on full SettingsStore instead of narrower AnalysisSettingsStore. This increases coupling slightly but eliminates the sync obligation. The single-lock approach is simpler and equally correct.

2. **C3 (UDP ports):** Changing the YAML config format from `data_listen: "0.0.0.0:9000"` to `data_host`/`data_port` is a breaking config change. Existing Pi deployments with `config.pi.yaml` would need updating. Must check if any deployed YAML files use the old format.

3. **L1 (numpy acceptance):** Making vibration_strength.py import numpy removes its "dependency-free" nature. Any tool that imported it without numpy would break. Must verify no such tool exists (confirmed: simulator already imports numpy, firmware is C++).

## Required Documentation Updates
- `docs/ai/repo-map.md`: remove analysis_settings.py reference, update settings description
- `.github/copilot-instructions.md`: remove any reference to AnalysisSettingsStore

## Required AI Instruction Updates
- Add to general.instructions.md: "Do not create parallel in-memory stores for the same logical state. Use a single store with scoped accessor methods."
- Add to general.instructions.md: "Do not create host:port combined strings only to immediately parse them back. Use separate host and port fields."

## Required Test Updates
- Remove hygiene test for analysis_settings.py import isolation
- Update tests that construct AnalysisSettingsStore directly
- Update registry tests for merged snapshot methods
- Remove `test_network_ports_single_source_of_truth`
- Update fft.py tests if float_list usage changes

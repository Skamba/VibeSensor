# Chunk 4: Configuration & Operational Simplification

## Mapped Findings

| ID | Original Finding | Source Subagent | Validation Status |
|----|-----------------|-----------------|-------------------|
| H1 | ProcessingConfig exposes 11 DSP/UI knobs that no deployment overrides | Operational/Config | **Validated** |
| H3 | update.server_repo configurable in 4-5 places, never changed | Operational/Config | **Validated** |
| D2 | settings_kv general KV abstraction stores only one key | Persistence & Schema | **Validated** |
| C1 | Update status persist() on every mutation | Data Flow & State | **Validated** |
| B1 | CommandRunner ABC in hotspot/self_heal.py unnecessary hierarchy | Abstraction & Indirection | **Validated** |
| H2 | hotspot_nmcli.sh embeds Python config reader duplicating defaults | Operational/Config | **Validated, downgraded** |

## Validation Outcomes

### H1: ProcessingConfig over-configuration — VALIDATED
Confirmed in `config.py`: `ProcessingConfig` has 11 fields including `sample_rate_hz`, `waveform_seconds`, `waveform_display_hz`, `ui_push_hz`, `ui_heavy_push_hz`, `fft_update_hz`, `fft_n`, `spectrum_min_hz`, `spectrum_max_hz`, `client_ttl_seconds`, `accel_scale_g_per_lsb`. The `__post_init__` has ~90 lines of clamping logic. Zero deployment configs override any of these fields.

Fields to promote to constants: `waveform_display_hz`, `ui_push_hz`, `ui_heavy_push_hz`, `fft_update_hz`, `fft_n`, `spectrum_min_hz`, `spectrum_max_hz` (7 fields).

Fields to keep configurable: `sample_rate_hz` (fallback before sensor reports), `waveform_seconds` (memory bound), `client_ttl_seconds` (operational), `accel_scale_g_per_lsb` (alternative sensor escape hatch).

### H3: update.server_repo scattered declarations — VALIDATED
Confirmed: `"Skamba/VibeSensor"` appears as:
1. `DEFAULT_CONFIG["update"]["server_repo"]` in `_config_defaults.py`
2. Config field `UpdateConfig.server_repo` in `config.py`
3. `_DEFAULT_REPO` constant in `release_fetcher.py`
4. `_DEFAULT_FIRMWARE_REPO` in `firmware_cache.py`
5. `VIBESENSOR_SERVER_REPO` env var read in `update/manager.py` and `release_fetcher.py`

The `manager.py` fallback is `os.environ.get("VIBESENSOR_SERVER_REPO", "")` (empty string), while `release_fetcher.py` fallback is the correct repo slug. This is an inconsistency.

### D2: settings_kv single-key abstraction — VALIDATED
Confirmed: `settings_kv` table is a general KV store but only ever stores key `"settings_snapshot"`. `get_setting(key)` / `set_setting(key, value)` are the generic API. `get_settings_snapshot()` / `set_settings_snapshot()` hardcode the key string.

**Refinement**: While the KV table is over-general, replacing it with a single-row table requires a schema migration. Since D1 (Chunk 1) already bumps the schema version, this change can piggyback. However, the simplification gain is modest — it's 2 method signatures and a magic constant. Given the effort-to-value ratio, I'll keep this finding but scope it to: remove the generic `get_setting`/`set_setting` methods (fold them into `get_settings_snapshot`/`set_settings_snapshot` as direct SQL) without changing the table DDL.

### C1: Update status persist() on every mutation — VALIDATED
Confirmed: `UpdateStatusTracker` in `update/status.py` calls `self.persist()` on every mutation: `start_job`, `transition`, `set_runtime`, `log`, `add_issue`, `extend_issues`, `fail`, `mark_success`, `finish_cleanup`. The `log()` method is called for every subprocess command invocation, producing 30-80+ fsync calls per update.

Simplification: Only persist on phase transitions (`start_job`, `transition`, `fail`, `mark_success`, `finish_cleanup`). Skip persist in `log()`, `set_runtime()`, and `add_issue()`/`extend_issues()`.

### B1: CommandRunner ABC in hotspot — VALIDATED
Confirmed: `CommandRunner(ABC)` with `@abstractmethod run()`, `SubprocessRunner(CommandRunner)` as the only real implementor. Tests define `_FakeRunner(CommandRunner)`. The `update/runner.py` module solves the same problem without an ABC — just a concrete class with a docstring saying "Override for testing."

### H2: hotspot_nmcli.sh config duplication — VALIDATED, DOWNGRADED
Confirmed: the shell script has an inline Python heredoc reading config. However, this script runs as root before the Python venv is available — it genuinely cannot `import vibesensor`. The duplication is a real maintenance hazard but the fix requires creating a CLI entry point that works outside the venv, which is infrastructure work beyond simplification scope. **Downgrade to out-of-scope** — the finding is valid but the fix is additive (new CLI binary), not simplifying.

## Implementation Steps

### Step 1: Promote ProcessingConfig constants (H1)

1. Create/extend `vibesensor/constants.py` with new processing constants:
   ```python
   WAVEFORM_DISPLAY_HZ = 30
   UI_PUSH_HZ = 10
   UI_HEAVY_PUSH_HZ = 1
   FFT_UPDATE_HZ = 5
   FFT_N = 2048
   SPECTRUM_MIN_HZ = 0.0
   SPECTRUM_MAX_HZ = 200.0
   ```
2. Remove these 7 fields from `ProcessingConfig` dataclass
3. Remove the corresponding ~80 lines of `__post_init__` clamping code
4. Remove these keys from `DEFAULT_CONFIG["processing"]` in `_config_defaults.py`
5. Remove them from `config.example.yaml`
6. Update all consumers that read from `config.processing.fft_n` etc. to import from `constants.py` instead:
   - `runtime/builders.py`
   - `processing/` modules
   - `runtime/processing_loop.py`
   - `runtime/ws_broadcast.py`
7. Verify with `make typecheck-backend`

### Step 2: Consolidate update.server_repo (H3)

1. Define `GITHUB_REPO: str = "Skamba/VibeSensor"` in `vibesensor/constants.py` as the single source of truth
2. In `release_fetcher.py`:
   - Remove `_DEFAULT_REPO` constant
   - Read `os.environ.get("VIBESENSOR_SERVER_REPO")` only here
   - Fall back to `GITHUB_REPO` from constants
3. In `firmware_cache.py`:
   - Remove `_DEFAULT_FIRMWARE_REPO` constant
   - Import `GITHUB_REPO` from constants
4. Remove `server_repo` from:
   - `DEFAULT_CONFIG["update"]` in `_config_defaults.py`
   - `UpdateConfig` dataclass in `config.py`
   - `config.example.yaml`
5. In `update/manager.py`:
   - Remove `os.environ.get("VIBESENSOR_SERVER_REPO", "")` fallback
   - The repo slug now comes only from `release_fetcher.py` via `GITHUB_REPO`
6. Fix the empty-string inconsistency

### Step 3: Simplify settings_kv access (D2)

1. In `HistoryDB`:
   - Make `get_setting()` and `set_setting()` private (`_get_setting`, `_set_setting`)
   - Or inline their SQL into `get_settings_snapshot()` / `set_settings_snapshot()`
2. Remove the public generic key-based API
3. Replace the magic string `"settings_snapshot"` with a constant or inline it
4. Keep the table DDL unchanged (no schema migration needed)

### Step 4: Reduce update status persist frequency (C1)

1. In `UpdateStatusTracker` (`update/status.py`):
   - Remove `self.persist()` from `log()` method
   - Remove `self.persist()` from `set_runtime()` method
   - Remove `self.persist()` from `add_issue()` and `extend_issues()` methods
   - Keep `self.persist()` in: `start_job()`, `transition()`, `fail()`, `mark_success()`, `finish_cleanup()`
2. Add a `flush()` public method that calls `persist()` for callers that need explicit flush
3. The in-memory state (`self._status`) remains always-consistent for reads

### Step 5: Remove CommandRunner ABC in hotspot (B1)

1. In `hotspot/self_heal.py`:
   - Rename `SubprocessRunner` to `CommandRunner`
   - Remove the `CommandRunner(ABC)` base class
   - Make the `run()` method concrete (it already is in `SubprocessRunner`)
   - Remove ABC/abstractmethod imports
2. In `tests/hotspot/test_hotspot_self_heal.py`:
   - Update `_FakeRunner(CommandRunner)` — it now subclasses the concrete class (same pattern as `update/runner.py`)

### Step 6: Verify

1. `ruff check apps/server/`
2. `make typecheck-backend`
3. `pytest -q apps/server/tests/config/ apps/server/tests/update/ apps/server/tests/hotspot/ apps/server/tests/history_db/`
4. Full: `pytest -q apps/server/tests/ -m "not selenium"`

## Dependencies on Other Chunks

- Schema-related changes (D2) don't require a version bump since we're not changing table DDL
- H1 values may be referenced by code touched in Chunk 3 (analysis constants) — execute after Chunk 3
- Independent of Chunk 5

## Risks and Tradeoffs

- **H1 constant promotion**: If a future sensor has different hardware requirements, these constants would need to become configurable again. Mitigated by commenting that they're sensor-specific and can be promoted back to config if a second sensor type is supported.
- **C1 crash recovery**: Reducing persist frequency means the status file may not reflect the very latest log entries if the server crashes mid-update. Phase boundaries are still persisted, so the UI shows the correct overall state.
- **H2 out of scope**: The hotspot config duplication remains. Document it as a known complexity.

## Validation Steps

- `ruff check apps/server/`
- `make typecheck-backend`
- `pytest -q apps/server/tests/`
- Verify config loading: `python -c "from vibesensor.config import load_config; load_config()"`

## Documentation Updates

- Remove processing knobs from `config.example.yaml`
- Remove `server_repo` from `config.example.yaml`
- Update `docs/ai/repo-map.md` if config structure changes

## AI Instruction Updates

- Add to `general.instructions.md`:
  - "Do not expose DSP/hardware-tuned parameters as user-facing config unless operators actually need to change them. Use constants for values tied to specific hardware."
  - "Do not scatter a single identity string (repo slug, service name) across multiple files. Define it once as a constant."
  - "Prefer erroring on invalid config over silently clamping. Clamping hides misconfiguration."

## Test Updates

- Update config tests that verify ProcessingConfig validation (remove clamping tests for promoted constants)
- Update update tests that mock `server_repo` config
- Update hotspot tests for concrete `CommandRunner`

## Simplification Crosswalk

| Finding | Steps | Removable | Verification |
|---------|-------|-----------|-------------|
| H1 | Step 1 | 7 config fields, ~80 lines clamping code, 7 YAML keys | config loads, no clamping warnings |
| H3 | Step 2 | 4-5 scattered repo slug declarations, inconsistent fallback | single constant, env var override works |
| D2 | Step 3 | Generic `get_setting`/`set_setting` public API | settings load/save works |
| C1 | Step 4 | ~5 unnecessary persist() calls | update workflow works, fewer fsyncs |
| B1 | Step 5 | ABC + abstractmethod, SubprocessRunner indirection | hotspot tests pass |
| H2 | N/A | Out of scope — fix is additive, not simplifying | Documented as known complexity |

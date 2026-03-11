# Chunk 1: Config, Operations, and Dead Code Cleanup

## Execution order: 1 of 5 (first — independent, bug fix, quick wins)

## Mapped Findings

| ID | Original Finding | Validation Result |
|----|-----------------|-------------------|
| D1 | Dead config knobs (`clients_json_path`, `metrics_log_path`) | CONFIRMED — `clients_json_path` is parsed/logged but never consumed by any runtime service. `metrics_log_path` is dead for I/O but has one side-effect: derives `history_db_path` fallback when not explicitly set. `log_metrics` is NOT dead (controls MetricsLogger.enabled). `append_jsonl_records` has zero production callers. |
| D2 | Hotspot self-heal service calls dead module path | CONFIRMED BUG — `vibesensor-hotspot-self-heal.service` invokes `python -m vibesensor.hotspot_self_heal` but that module doesn't exist; it was moved to `vibesensor.hotspot.self_heal`. The pyproject.toml entry point is correct. |
| D3 | AP defaults duplicated in `hotspot_nmcli.sh` | CONFIRMED — Shell script embeds a Python `defaults` dict with "Keep in sync" comment. Values match `_config_defaults.py` today but have no enforcement mechanism. |
| D4 | `config.example.yaml` manually mirrors `DEFAULT_CONFIG` | CONFIRMED — File header admits it mirrors `documented_default_config()`. Currently aligned but no CI guard. Only consumed by `install_pi.sh` preflight check and human reading. |
| D5 | Dual-layer `_`-field filtering | CONFIRMED as dead code — `_sanitize_for_storage` strips `_report_template_data` which nothing produces. `strip_internal_fields` filters top-level `_`-prefixed keys but none exist at the top level. Both functions are no-ops in practice. |
| E6 | `contracts.py` leftover wrapper module | CONFIRMED — 35-line module with 2 constants. `LOCATION_CODES` has 1 consumer (`locations.py`), `NETWORK_PORTS` has 2 (`_config_defaults.py`, `sim_sender.py`). Docstring says it was formerly runtime-loaded from JSON files. |

## Root Causes

These findings share a common root cause: incremental architecture changes that left behind scaffolding, dead paths, and duplicate definitions. The config surface accumulated fields for a pre-SQLite persistence era (`clients_json_path`, `metrics_log_path`). The hotspot module moved to a subpackage without updating the systemd service. The contracts module was a transitional artifact from the `libs/shared/` inlining. The `_`-field filtering was defense-in-depth that became fully inert as data shapes changed.

## Relevant Code Paths and Components

### D1: Dead config knobs
- `apps/server/vibesensor/config.py` — `AppConfig` class, `StorageConfig`, `LoggingConfig`: parse `clients_json_path`, `metrics_log_path`, startup validation
- `apps/server/vibesensor/_config_defaults.py` — `DEFAULT_CONFIG` dict: contains `storage.clients_json_path` and `logging.metrics_log_path` defaults
- `apps/server/vibesensor/runtime/builders.py` — wires `log_metrics` to `MetricsLoggerConfig.enabled` (this is NOT dead)
- `apps/server/vibesensor/registry.py` — `ClientRegistry` loads names from SQLite, never references `clients_json_path`
- `apps/server/vibesensor/runlog.py` — `append_jsonl_records` in `__all__` but zero production callers
- Config files: `config.yaml`, `config.dev.yaml`, `config.docker.yaml`, `config.example.yaml`, `config.pi.yaml` — may reference these keys

### D2: Hotspot self-heal
- `apps/server/systemd/vibesensor-hotspot-self-heal.service` — ExecStart line has wrong module path
- `apps/server/vibesensor/hotspot/self_heal.py` — correct module
- `apps/server/pyproject.toml` — correct entry point
- `apps/server/scripts/hotspot_self_heal.py` — 7-line stub script

### D3: AP defaults duplication
- `apps/server/scripts/hotspot_nmcli.sh` — inline Python defaults dict (~L143)
- `apps/server/vibesensor/_config_defaults.py` — `DEFAULT_CONFIG["ap"]` (source of truth)

### D4: Example config mirror
- `apps/server/config.example.yaml` — manual mirror
- `apps/server/vibesensor/_config_defaults.py` — authoritative defaults
- `apps/server/vibesensor/config_preflight.py` — has `documented_default_config()` that could generate the file

### D5: Dead `_`-field filtering
- `apps/server/vibesensor/history_db/__init__.py L51-54` — `_sanitize_for_storage()` pops dead key
- `apps/server/vibesensor/history_services/helpers.py L41-42` — `strip_internal_fields()` filters non-existent keys
- Callers: `history_db/__init__.py:store_analysis`, `history_services/runs.py:get_run`, `history_services/runs.py:get_insights`, `history_services/exports.py:build_export`

### E6: contracts.py dissolution
- `apps/server/vibesensor/contracts.py` — source
- `apps/server/vibesensor/locations.py` — imports `LOCATION_CODES`
- `apps/server/vibesensor/_config_defaults.py` — imports `NETWORK_PORTS`
- `apps/server/vibesensor/simulator/sim_sender.py` — imports `NETWORK_PORTS`
- `apps/server/tests/analysis/test_single_source_of_truth.py` — imports `NETWORK_PORTS`

## Simplification Approach

### D1: Remove dead config fields
1. Remove `clients_json_path` from `StorageConfig` in `config.py`
2. Remove `clients_json_path` from `DEFAULT_CONFIG` in `_config_defaults.py`
3. Remove `clients_json_path` from startup log format string
4. For `metrics_log_path`: since it's used to derive `history_db_path` fallback, replace the derivation with a direct default path `data/history.db` and remove `metrics_log_path` entirely
5. Remove `metrics_log_path` from `LoggingConfig`, `DEFAULT_CONFIG`, startup log
6. Keep `log_metrics` (it's alive — maps to `MetricsLoggerConfig.enabled`)
7. Remove `append_jsonl_records` from `runlog.py.__all__` but KEEP the function (tests use it)
8. Update all config overlay files (`config.dev.yaml`, `config.docker.yaml`, `config.pi.yaml`) to remove dead keys
9. Update `config.example.yaml` to remove dead fields

### D2: Fix hotspot self-heal service
1. Change `ExecStart` in `vibesensor-hotspot-self-heal.service` from `python -m vibesensor.hotspot_self_heal` to use the installed entry point `vibesensor-hotspot-self-heal`
2. Delete `apps/server/scripts/hotspot_self_heal.py` (7-line stub that duplicates the entry point)

### D3: Eliminate AP defaults duplication
1. Replace the inline `defaults` dict in `hotspot_nmcli.sh` with a Python import from `_config_defaults.py`:
   ```python
   from vibesensor._config_defaults import DEFAULT_CONFIG
   defaults = DEFAULT_CONFIG["ap"]
   ```
2. Remove the "Keep in sync" comment since there's now one source of truth

### D4: Auto-generate example config
1. Add a `generate-example-config` Makefile target that calls `config_preflight.py` or a simple script to emit YAML from `documented_default_config()`
2. Add a CI hygiene check that verifies `config.example.yaml` matches `documented_default_config()` output
3. OR simpler: delete `config.example.yaml` and point docs/scripts to `vibesensor-config-preflight --dump-defaults` instead

On validation, the simpler approach (option 3) is better: delete the file, update `install_pi.sh` to not validate it, and add a note to README pointing to the preflight tool for default reference. This removes the drift vector entirely.

### D5: Remove dead filtering code
1. Delete `_sanitize_for_storage()` function from `history_db/__init__.py`
2. Remove the call to `_sanitize_for_storage(analysis)` in `store_analysis`
3. Keep `strip_internal_fields` as defense-in-depth (it adds no cost and protects against future keys)
4. Add a comment to `strip_internal_fields` noting it's defense-in-depth and currently a no-op

### E6: Dissolve contracts.py
1. Move `LOCATION_CODES` dict into `locations.py` (its sole consumer)
2. Move `NETWORK_PORTS` dict into `_config_defaults.py` (its primary consumer)
3. Update `sim_sender.py` to import `NETWORK_PORTS` from `_config_defaults`
4. Update test import in `test_single_source_of_truth.py`
5. Delete `contracts.py`

## Implementation Sequence

1. D2 first (bug fix — most critical)
2. D1 (dead config removal — foundational cleanup)
3. E6 (dissolve contracts.py — simple, reduces file count)
4. D5 (dead filtering code)
5. D3 (AP defaults dedup)
6. D4 (example config)

## Dependencies on Other Chunks

- E6 relates to E5 (LOCATION_CODES duplication) in Chunk 4 — after dissolving contracts.py, the LOCATION_CODES source of truth moves to locations.py, which is cleaner for the sync guard in Chunk 4
- D1 will change config.example.yaml, which D4 also touches — do D1 first, D4 last

## Risks and Tradeoffs

- D1: Removing `metrics_log_path` changes the `history_db_path` fallback derivation. Must verify the new default path still resolves correctly in all deployment configs.
- D2: Changing the service file requires Pi image rebuild to take effect. Not a code risk but a deployment consideration.
- D3: The shell script change introduces a Python import inside an embedded Python snippet. Must ensure the venv is activated when the script runs (it already is — the script runs within the venv context).
- D4: Removing `config.example.yaml` removes a human-readable reference. Mitigated by the `--dump-defaults` CLI.
- E6: Changing import paths requires updating any mypy config entries.

## Validation Steps

1. Run targeted tests: `pytest -q apps/server/tests/app/` (config tests)
2. Run `make lint` and `make typecheck-backend`
3. Verify config loading still works: `vibesensor-config-preflight config.yaml`
4. Run broader test suite: `python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests`

## Required Documentation Updates

- Update `config.example.yaml` (or delete it per D4 plan)
- Update `docs/ai/repo-map.md` if contracts.py is mentioned
- Update `.github/copilot-instructions.md` if contracts.py is mentioned
- Update `apps/server/README.md` config section if it references dead fields

## Required AI Instruction Updates

- Add guidance to `.github/instructions/general.instructions.md` under complexity hygiene:
  - "Do not add config fields that are not consumed by any runtime code path"
  - "Do not duplicate defaults across config files and shell scripts"
  - "When moving a module to a subpackage, update ALL consumers including systemd services and scripts"
- Update the contracts/LOCATION_CODES references in copilot-instructions.md

## Required Test Updates

- Update `test_release_validation.py` if it validates `config.example.yaml`
- Update `test_single_source_of_truth.py` import for `NETWORK_PORTS`
- Add hygiene test verifying no dead config fields (optional, low priority)

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Areas Changed | What's Removed | Verification |
|---------|-----------|------------|-------|---------------|----------------|--------------|
| D1 | CONFIRMED (clients_json_path dead, metrics_log_path dead for I/O) | Pre-SQLite persistence paths never cleaned up | Remove from config.py, _config_defaults.py, config overlays | config.py, _config_defaults.py, 4 config files | ~30 lines config scaffolding, 2 dead fields, startup validation of dead path | Config preflight passes, tests pass |
| D2 | CONFIRMED BUG | Module rename missed systemd update | Fix ExecStart, delete stub script | systemd service, scripts/ | 7-line stub script | Service file references correct module |
| D3 | CONFIRMED | Shell script needed standalone defaults | Replace inline defaults with import | hotspot_nmcli.sh | ~8 lines of duplicate defaults | hotspot_nmcli.sh reads from single source |
| D4 | CONFIRMED | Standard OSS pattern without automation | Delete config.example.yaml, update install_pi.sh | config.example.yaml, install_pi.sh | ~50 lines manual mirror file | install_pi.sh works without example file |
| D5 | CONFIRMED dead code | Data shape changed, filtering became inert | Delete _sanitize_for_storage, keep strip_internal_fields | history_db/__init__.py | ~10 lines dead function + call | store_analysis still works, tests pass |
| E6 | CONFIRMED | Transitional artifact from libs/shared inlining | Move constants to consumers, delete module | contracts.py, locations.py, _config_defaults.py, sim_sender.py | 35-line module | All imports resolve, tests pass |

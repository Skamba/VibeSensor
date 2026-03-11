# Chunk 5: Configuration, Tooling & Dev-Workflow Simplification

## Mapped Findings

| ID | Original Finding | Source Subagents | Validation Result |
|----|-----------------|------------------|-------------------|
| H1+H3 | Config knob bloat — 24 of 31 fields never overridden in any YAML config file | Config/Knobs | **VALIDATED** — 24 fields in _config_defaults.py are never overridden by config.yaml, config.dev.yaml, config.docker.yaml, or config.pi.yaml. 16 are strong inline candidates (hardware constants, internal tuning, always-true booleans). 8 are weaker candidates (network identity, listen addresses) that are legitimate per-deployment knobs even if currently constant. |
| H2 | Update config dataclass proliferation — 5 intermediary config dataclasses in update/manager.py, 3 of which are single-consumer single-use wrappers | Config/Knobs | **VALIDATED** — UpdateReleaseConfig (1 field), UpdateServiceControlConfig (2 constant fields), UpdateWifiConfig (12 fields, 10 are module constants). These 3 are eliminable. UpdateInstallerConfig (4 fields) and UpdateValidationConfig (2 fields) are border cases used for test injection. |
| G1+G2+G3 | Makefile test target redundancy — 3 coverage variants differ by one flag | CI Tooling | **PARTIALLY VALIDATED** — 3 coverage targets (coverage, coverage-html, coverage-strict) are almost identical. However, none are "aliases documented as use X instead" so the strict instruction doesn't apply. The consolidation to a single parameterized target is still worthwhile but low priority. |
| I1 | Contract sync pipeline complexity — openapi-typescript for WS types requires synthetic OpenAPI 3.1 envelope wrapping | Pipeline/Sync | **VALIDATED** — sync_shared_contracts_to_ui.mjs has a 4-5 step pipeline. WS types are plain JSON Schema force-wrapped into an OpenAPI envelope. Justified for HTTP types (4651-line OpenAPI schema). Questionable for WS types (645-line JSON Schema, 12 type aliases). Single-tool uniformity is the reason. |
| I3 | Ghost vibesensor.core references — stale paths in 10+ docs/config/build files after package inlining | Cross-cutting | **VALIDATED** — 10 stale references confirmed across .github/copilot-instructions.md, .github/instructions/backend.instructions.md, README.md, BOUNDARIES.md, docs/ai/repo-map.md, docs/metrics.md, docs/analysis_pipeline.md, tools/tests/heuristics_audit.py, infra/pi-image/pi-gen/build.sh. The build.sh reference is **actively broken** (import will fail). |
| A3 | UI feature factory abstraction | Architecture | **REJECTED** — Investigation shows a clean, flat composition pattern. FeatureDepsBase is a 3-field interface extended by all 6 feature deps. No class hierarchy, no abstract factory, no over-engineering. No action needed. |

## Root Causes

1. **Config over-generality**: _config_defaults.py was designed for maximum flexibility, exposing every internal tuning parameter as a YAML-overridable knob. In practice, hardware constants (sample_rate_hz, sensor_model) and internal design constants (waveform_seconds, data_queue_maxsize) never vary.
2. **Config-as-interface habit**: Each subsystem in update/ receives a config dataclass, even when the subsystem reads only 1-2 values that are already constants in its own module.
3. **Documentation drift**: The vibesensor.core package was inlined into vibesensor/ but references across 10+ files were not updated.
4. **Pipeline uniformity**: Using openapi-typescript for both HTTP and WS schemas keeps one tool, but forces WS schemas through a synthetic OpenAPI wrapper.

## Simplification Approach

### Step 1: Fix ghost vibesensor.core references (IMMEDIATE — one is actively broken)

Update 10 stale references:

| File | Fix |
|------|-----|
| `.github/copilot-instructions.md` L20 | `vibesensor/core/vibration_strength.py` → `vibesensor/vibration_strength.py` |
| `.github/instructions/backend.instructions.md` L23 | `vibesensor.core.vibration_strength` → `vibesensor.vibration_strength` |
| `README.md` L45 | `apps/server/vibesensor/core/vibration_strength.py` → `apps/server/vibesensor/vibration_strength.py` |
| `apps/server/vibesensor/BOUNDARIES.md` L18-20 | `vibesensor.core` → `vibesensor`, `vibesensor/core/*.py` → `vibesensor/vibration_strength.py`, `vibesensor/strength_bands.py` |
| `docs/ai/repo-map.md` L21 | Remove `vibesensor/core/` line or update path |
| `docs/metrics.md` L27, L43 | `vibesensor/core/vibration_strength.py` → `vibesensor/vibration_strength.py`, same for `strength_bands.py` |
| `docs/analysis_pipeline.md` L42 | `vibesensor.core` → `vibesensor` |
| `tools/tests/heuristics_audit.py` L84-86 | Update path check to `apps/server/vibesensor` |
| `infra/pi-image/pi-gen/build.sh` L999 | `import vibesensor.core` → `import vibesensor.vibration_strength` (or equivalent valid import) |

### Step 2: Inline strong-candidate config constants

Convert 16 never-overridden fields from YAML-configurable to Python constants:

**Processing section** → constants in the consuming module:
- `sample_rate_hz = 800` — hardware-determined
- `waveform_seconds = 8` — buffer design constant
- `client_ttl_seconds = 120` — internal timeout
- `accel_scale_g_per_lsb = None` — auto-detect default

**Logging section** → constants in the consuming module:
- `metrics_log_hz = 4` — internal tuning
- `no_data_timeout_s = 15.0` — internal timeout
- `sensor_model = "ADXL345"` — hardware constant
- `shutdown_analysis_timeout_s = 30` — internal timeout
- `persist_history_db = True` — always true
- `log_metrics = True` — always true

**UDP section** → constants in the consuming module:
- `data_queue_maxsize = 1024` — internal tuning

**AP self-heal section** → constants in self_heal module:
- `diagnostics_lookback_minutes = 5`
- `min_restart_interval_seconds = 120`
- `allow_disable_resolved_stub_listener = False`

**GPS section** → constants in GPS module:
- `gpsd_host = "127.0.0.1"` — standard localhost
- `gpsd_port = 2947` — standard gpsd port

Process:
1. For each field, find all readers (grep for the config field name)
2. Replace config reads with direct constant access
3. Remove the field from _config_defaults.py and the config dataclass
4. Remove from config.py parsing
5. Verify no YAML file overrides it (already confirmed — none do)

### Step 3: Eliminate 3 update config dataclasses

**UpdateReleaseConfig** (1 field: `rollback_dir`):
- Replace with passing `rollback_dir: Path` directly to `UpdateReleaseService.__init__()`
- Delete the dataclass

**UpdateServiceControlConfig** (2 fields: module constants):
- Inline `UPDATE_SERVICE_NAME` and `UPDATE_RESTART_UNIT` directly in `schedule_service_restart()`
- Delete the dataclass

**UpdateWifiConfig** (12 fields, 10 are constants):
- Let the wifi module use its own constants directly instead of receiving them through a config bundle
- Pass only the 2 varying fields (`ap_con_name`, `wifi_ifname`) as parameters
- Delete the dataclass

### Step 4: Consolidate Makefile coverage targets

Replace 3 targets with 1 parameterized target:

```makefile
coverage:  ## Run coverage (use COV_OPTS for extras: COV_OPTS="--cov-report=html --cov-fail-under=80")
	pytest --cov=vibesensor --cov-report=term $(COV_OPTS) apps/server/tests
```

Remove `coverage-html` and `coverage-strict`. Document:
- `make coverage` — basic terminal report
- `make coverage COV_OPTS="--cov-report=html"` — HTML report
- `make coverage COV_OPTS="--cov-fail-under=80"` — strict threshold

### Step 5: Clean stale build artifacts

- Add `apps/server/build/` to `.gitignore` if not already present
- Remove `apps/server/build/` from git tracking (it contains stale compiled artifacts referencing vibesensor_core)

### Step 6: Simplify contract sync WS path (LOW PRIORITY — defer if time-constrained)

The WS sync path in `sync_shared_contracts_to_ui.mjs` wraps plain JSON Schema in a synthetic OpenAPI envelope. This works but is unnecessarily complex. A simpler approach:
- Use `json-schema-to-typescript` for WS types
- Keep `openapi-typescript` only for HTTP types

However, the current approach is functional and the cost is ~30 lines of extra code. **Defer this unless a natural opportunity arises.**

## Simplification Crosswalk

### H1+H3 → Config knob bloat
- **Validation**: 24/31 fields never overridden; 16 are strong inline candidates
- **Root cause**: Over-general config designed for maximum flexibility
- **Steps**: Inline 16 constants, remove from config dataclass/defaults/parsing
- **Removable**: 16 fields from _config_defaults.py, corresponding dataclass fields, parsing code
- **Verification**: All config files still load; all tests pass; no runtime changes

### H2 → Update config dataclass proliferation
- **Validation**: 3 eliminable dataclasses (UpdateReleaseConfig, UpdateServiceControlConfig, UpdateWifiConfig)
- **Root cause**: Config-as-interface habit
- **Steps**: Delete 3 dataclasses, pass values directly or use module constants
- **Removable**: 3 dataclass definitions, construction code in __init__
- **Verification**: Update tests pass; update workflow runs correctly

### G1+G2+G3 → Makefile test target redundancy
- **Validation**: 3 coverage variants nearly identical
- **Steps**: Consolidate to 1 parameterized target
- **Removable**: 2 Makefile targets (~6 lines)
- **Verification**: `make coverage` works; documented alternatives work

### I1 → Contract sync pipeline
- **Validation**: WS path has unnecessary OpenAPI wrapping
- **Steps**: DEFER — functional, low impact
- **Removable**: Potentially ~30 lines, but not worth the risk/effort now
- **Verification**: N/A (deferred)

### I3 → Ghost vibesensor.core references
- **Validation**: 10 stale references, 1 actively broken (build.sh)
- **Steps**: Fix all 10 references to current paths
- **Removable**: 0 lines (rewrites, not deletions)
- **Verification**: `grep -r "vibesensor.core\|vibesensor/core" docs/ .github/ README.md tools/ infra/` returns 0

### A3 → UI feature factory (REJECTED)
- Clean composition pattern, no over-engineering
- No action needed

## Dependencies on Other Chunks

- Ghost reference fixes (Step 1) are independent of all other chunks
- Config inlining (Step 2) is independent but should be done after Chunk 3 (which may change how some config values are accessed in metrics_log)
- Update dataclass elimination (Step 3) is independent
- Makefile changes (Step 4) are independent

## Risks and Tradeoffs

1. **Config inlining**: Makes these values non-configurable via YAML. Risk: an advanced user might want to change sample_rate_hz for different hardware. Mitigated: these are hardware-determined values; changing hardware would require code changes anyway.
2. **Build artifact removal**: If someone depends on `apps/server/build/`, removing it from git would break them. Risk: very low — build artifacts should be generated, not committed. Mitigated: .gitignore entry prevents future accidental commits.
3. **Makefile consolidation**: Users with `make coverage-html` in scripts or muscle memory will need to adapt. Risk: low — this is a dev convenience target.

## Validation Steps

1. `grep -r "vibesensor.core\|vibesensor/core" docs/ .github/ README.md tools/ infra/ apps/server/vibesensor/BOUNDARIES.md` — returns 0
2. `make lint` — clean
3. `make typecheck-backend` — clean
4. `pytest -q apps/server/tests/` — all tests pass
5. Config loading: `python -c "from vibesensor.config import load_config; load_config('apps/server/config.yaml')"` — no errors
6. Update tests: `pytest -q apps/server/tests/update/` — all pass
7. `make test-all` — full CI-parity suite passes

## Required Documentation Updates

- All 10 ghost vibesensor.core references fixed (Step 1)
- docs/ai/repo-map.md — update config section to note which values are now constants
- README.md — update architecture section

## Required AI Instruction Updates

- .github/copilot-instructions.md — fix vibesensor/core path references
- .github/instructions/backend.instructions.md — fix vibesensor.core.vibration_strength reference
- Add: "Do not add config knobs for values that are hardware-determined, internal design constants, or always-true booleans. Use Python constants instead."

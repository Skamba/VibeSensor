# Chunk 5: Configuration, Structure & Guidance Cleanup

## Mapped Findings

| ID | Title | Validation | Status |
|----|-------|------------|--------|
| H1 | APSelfHealConfig.interval_seconds dead config field | VALID | Plan below |
| H2 | Triple AP defaults | VALID | Plan below |
| H3 | history_db_path absent from DEFAULT_CONFIG | VALID | Plan below |
| D2 | extra_json overflow column machinery never activated | PARTIALLY VALID | Plan below |
| J1 | analysis/report_mapping/ misplaced inside analysis/ | VALID | Plan below |
| J2 | AI guidance spans 12 files with duplication | VALID | Plan below |

## Root Causes

Configuration grew incrementally: `interval_seconds` was left behind when the self-heal switched
from daemon to systemd-timer pattern. AP defaults were duplicated when the shell script needed
config parsing without venv access. `history_db_path` was handled as a derived value instead of
an explicit default. The `extra_json` schema machinery was built for forward-extensibility that
never materialized. `report_mapping/` was placed in `analysis/` to avoid `report/ → analysis/`
imports but created the opposite coupling. AI guidance accumulated across multiple files as
VS Code added new instruction mechanisms.

## Validation Details

### H1: interval_seconds Dead Config Field (VALID)

`APSelfHealConfig.interval_seconds` is defined, validated, and stored but never read by any
Python code. The actual execution interval is controlled by the systemd timer file.

### H2: Triple AP Defaults (VALID)

Confirmed: AP defaults (`ssid: VibeSensor`, `psk: ""`, `ip: 10.4.0.1/24`, etc.) appear in both
`_config_defaults.py` and embedded Python in `hotspot_nmcli.sh`. The shell script falls back
to its own hardcoded defaults if YAML parsing fails.

### H3: history_db_path Absent from DEFAULT_CONFIG (VALID)

`DEFAULT_CONFIG["logging"]` has no `history_db_path`. `documented_default_config()` exists solely
to compute this derived value. `load_config` has its own inline fallback. Three derivations total.

### D2: extra_json Dead Machinery (PARTIALLY VALID)

The `extra_json` write/read machinery is fully implemented but `extra` is always empty because
`SensorFrame.to_dict()` only emits `_V2_KNOWN_KEYS` fields. The machinery is wasted computation
on the hot write path.

**Plan:** Remove the `extra_json` computation from the hot write/read paths. Keep the column in
the schema (dropping it requires a migration). Short-circuit by always writing NULL and skipping
the read-side merge.

### J1: analysis/report_mapping/ Misplaced (VALID)

All `report_mapping/` subfiles import from `report.report_data`. The dependency direction is
`analysis/report_mapping/ → report/`. The mapping logically belongs in `report/`.

### J2: AI Guidance Duplication (VALID)

`copilot-instructions.md` and `general.instructions.md` contain near-identical sections for
workflow, documentation maintenance, updater deployment, validation, and no-compat policies.

## Implementation Steps

### Step 1: Remove interval_seconds (H1)
1. Remove `interval_seconds` field from `APSelfHealConfig` in `config.py`
2. Remove its validation in `__post_init__`
3. Remove from `DEFAULT_CONFIG` in `_config_defaults.py`
4. Remove from `config.example.yaml`
5. Remove test cases that validate this field

### Step 2: Add comment linking AP defaults (H2)
1. In `hotspot_nmcli.sh`: add a comment above the defaults dict linking to `_config_defaults.py`
   as the canonical source: `# Defaults must match _config_defaults.py DEFAULT_CONFIG["ap"]`
2. Full deduplication would require the shell script to import from the venv Python, which is
   a larger change. For now, document the coupling explicitly.

### Step 3: Add history_db_path to DEFAULT_CONFIG (H3)
1. Add `"history_db_path": "data/history.db"` to `DEFAULT_CONFIG["logging"]`
2. Simplify `documented_default_config()` — the history_db_path computation is now in the default
3. Simplify `load_config` fallback for history_db_path

### Step 4: Short-circuit extra_json (D2)
1. In `_samples.py::sample_to_v2_row()`: remove the dict comprehension that computes `extra`,
   always append `None` for `extra_json`
2. Remove `_V2_KNOWN_KEYS` frozenset
3. In `v2_row_to_dict()`: skip the `safe_json_loads` for `extra_json`, don't merge
4. In `exports.py`: remove `EXPORT_CSV_COLUMN_SET` and `extras` branch in `flatten_for_csv`

### Step 5: Move analysis/report_mapping/ → report/mapping/ (J1)
1. Move `analysis/report_mapping/` directory to `report/mapping/`
2. Update all internal relative imports within the moved files
3. Update `analysis/__init__.py` to remove `map_summary` re-export
4. Update callers of `from vibesensor.analysis import map_summary` (likely in routes or services)
5. Update test imports

### Step 6: Deduplicate AI guidance (J2)
1. Make `general.instructions.md` the sole source for shared workflow rules (it has `applyTo: "**"`)
2. In `copilot-instructions.md`:
   - Keep only repo-overview, architecture constraints, common commands, and Pi access sections
   - Remove duplicated workflow, documentation maintenance, updater, validation, and no-compat sections
   - Add a pointer: "Shared workflow rules: see `.github/instructions/general.instructions.md`"
3. Merge `CLAUDE.md` content into `AGENTS.md` (they're identical pointer files)
4. Delete `CLAUDE.md`

### Step 7: Add anti-complexity guardrails to AI instructions
1. Add explicit guidance discouraging:
   - Dead config fields: "Remove config fields that are not read by any code path"
   - Duplicate defaults: "Maintain a single source of truth for default values"
   - Forward-extensibility machinery for cases that haven't materialized
   - Misplaced bridge modules
2. Add: "Prefer flat, direct structures. Only introduce grouping/wrapping when >3 consumers
   benefit from the indirection."

## Dependencies on Other Chunks
- J1 (report_mapping move) should come after Chunk 1 (which touches persistence subsystem)
  to avoid merge conflicts
- J2 (guidance dedup) is independent

## Risks
- Moving report_mapping/ changes import paths across analysis tests
- Removing interval_seconds is a config schema breaking change (accepted by repo policy)
- extra_json short-circuit: old DB rows with non-null extra_json would lose data on read —
  but since extra_json has never been populated, this is a non-risk

## Documentation Updates Required
- `docs/ai/repo-map.md`: update analysis/ and report/ package descriptions
- `config.example.yaml`: remove interval_seconds
- `.github/copilot-instructions.md`: deduplicate sections
- `AGENTS.md`: merge CLAUDE.md pointer

## Validation
- `pytest apps/server/tests/config/` for config changes
- `pytest apps/server/tests/analysis/` for report_mapping move
- `pytest apps/server/tests/report/` for report_mapping move
- Full `make test-all`
- `make typecheck-backend`

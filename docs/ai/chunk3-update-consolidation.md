# Chunk 3: Update Package Consolidation

## Mapped Findings

| ID | Title | Validation | Status |
|----|-------|------------|--------|
| A1/J3 | update/ over-decomposed into 11 enterprise-style files | VALID | Plan below |

## Root Causes

The `update/` package was decomposed using enterprise-Java SRP principles: one class per operation,
one config dataclass per class, one file per class. The result is 11 files with uniform structural
repetition (Config dataclass + Controller/Service class with identical `__init__` signatures).
Several files are thin enough to merge: `network.py` (~40 lines, single function), `validation.py`
(~50 lines, 2 tiny classes), `runtime_details.py` (~117 lines, single consumer). `manager.py`
imports from all 10 sibling modules.

## Validation Details

### A1/J3: Validated Merge Targets

**Files suitable for merging (thin stubs):**
- `network.py` (~40 lines, 1 function `parse_wifi_diagnostics`) → merge into `wifi.py`
- `validation.py` (~50 lines, `UpdatePrerequisiteValidator` + `UpdateValidationConfig`) → merge into `workflow.py`
- `runtime_details.py` (~117 lines, `UpdateRuntimeDetailsCollector`, only consumer is `manager.py`) → merge into `status.py`

**Files that stay (substantive):**
- `models.py` (~170 lines) — enums, dataclasses for state machine
- `status.py` (~250 lines) — `UpdateStatusTracker` + `UpdateStateStore`
- `installer.py` (~480 lines) — install/rollback/snapshot logic
- `workflow.py` (~280 lines) — orchestration + service controller
- `runner.py` (~130 lines) — command execution base, used by 7 sibling files
- `releases.py` (~90 lines) — GitHub release discovery
- `wifi.py` (~100 lines) — Wi-Fi controller
- `manager.py` (~200 lines) — public facade

**Counter-evidence:** The existing decomposition is explicitly defended in the backend instructions.
But the 3 stub files add navigational overhead without encapsulation benefit.

## Implementation Steps

### Step 1: Merge network.py into wifi.py
1. Move `parse_wifi_diagnostics()` function from `network.py` to `wifi.py`
2. Move any constants from `network.py` to `wifi.py`
3. Update imports in `manager.py` and any other consumers
4. Delete `network.py`

### Step 2: Merge validation.py into workflow.py
1. Move `UpdateValidationConfig` and `UpdatePrerequisiteValidator` into `workflow.py`
2. Update imports in `manager.py`
3. Delete `validation.py`

### Step 3: Merge runtime_details.py into status.py
1. Move `UpdateRuntimeDetailsCollector` into `status.py`
2. Move helper function `_hash_tree` along with it
3. Update import in `manager.py`
4. Delete `runtime_details.py`

### Step 4: Update __init__.py re-exports
1. Update `update/__init__.py` to reflect merged modules
2. Remove re-exports for deleted modules

### Step 5: Update manager.py imports
1. Change imports from deleted modules to their new locations
2. Verify import count drops from 10 to 7

### Step 6: Update tests
1. Update any test imports referencing deleted modules
2. Run update-related tests

## Dependencies on Other Chunks
- Independent of all other chunks

## Risks
- Low risk — pure file restructuring, no logic changes
- Config dataclasses stay in their new host files
- Backend instructions explicitly mentioned this module; update the guidance

## Documentation Updates Required
- `docs/ai/repo-map.md`: update update/ package description
- `.github/instructions/backend.instructions.md`: update update/ ownership

## Validation
- `pytest apps/server/tests/update/`
- `make typecheck-backend`
- Full `make test-all`

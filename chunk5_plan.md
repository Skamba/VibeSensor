# Chunk 5: Tooling, Config & Dependency Cleanup

## Mapped Findings

| ID | Original Title | Validation | Status |
|----|---------------|------------|--------|
| G2 | build_ui_static.py mini build-caching system | **Validated** — 108-line script with `_hash_tree()` (different from update/status.py version), `.npm-ci-lock.sha256` stateful cache, conflicting `--skip-npm-ci`/`--force-npm-ci` flags. | Proceed (simplify, don't delete) |
| I3 | uvloop redundant production dependency | **Validated** — Declared directly in pyproject.toml with platform guards. Zero `import uvloop` in codebase. Already transitive via `uvicorn[standard]`. | Proceed |
| H2 | config.yaml empty placeholder | **Validated** — 6 lines of comments only. Never read at runtime (overlay system reads config.dev/docker/pi.yaml). | Proceed |
| E3 | create_settings_routes 5-arg factory | **Validated** — 5 args: settings_store (16/17 handlers), gps_monitor (1/17), analysis_settings (2/17), apply_car_settings (5/17), apply_speed_source_settings (1/17). | Mostly resolved by Chunk 1's A3 |

## Root Complexity Drivers

1. **Hash-tree duplication**: Two different `_hash_tree()` implementations doing the same job. The build_ui_static.py version lacks error handling.
2. **Flag confusion**: `--skip-npm-ci` (unconditional skip) and `--force-npm-ci` (unconditional run) are mutually contradictory but both exist. The hash-cache logic handles the common case automatically.
3. **Phantom dependency**: uvloop is declared with elaborate platform/version guards but nobody imports it directly.
4. **Placeholder config**: An empty config.yaml adds confusion without providing value.
5. **Factory arg bloat**: 5 args where 2 are callback indirections (resolved by Chunk 1) and 1 serves a single route.

## Simplification Approach

### G2: Simplify build_ui_static.py caching

**Strategy**: Replace the local `_hash_tree()` with an import from `update.status`, and remove the conflicting skip/force flags (let the hash-cache handle it automatically).

**Steps**:
1. Remove the local `_hash_tree()` function (lines 18-29) from `build_ui_static.py`
2. Import `_hash_tree` from `vibesensor.update.status` (the production version with error handling)
3. Remove `--skip-npm-ci` and `--force-npm-ci` CLI flags — the `.npm-ci-lock.sha256` hash-cache logic handles everything:
   - If lockfile changed → run npm ci
   - If lockfile unchanged and node_modules exists → skip npm ci
   - If node_modules missing → run npm ci
4. For edge cases where a forced npm ci is truly needed, deleting `node_modules/` or `.npm-ci-lock.sha256` achieves the same result

**Risk note**: build_ui_static.py is a development tool, not production code. The import path assumes `vibesensor` is installed in the dev environment (which it is via `pip install -e ".[dev]"`).

### I3: Remove redundant uvloop direct dependency

**Steps**:
1. Remove the `"uvloop>=0.21,<1; python_version < '3.12' and sys_platform != 'win32'..."` line from pyproject.toml `dependencies`
2. Verify `uvicorn[standard]` (already a dependency) transitively provides uvloop with the same platform constraints
3. No code changes needed — nothing imports uvloop directly

### H2: Delete empty config.yaml

**Steps**:
1. Delete `apps/server/config.yaml` (6 lines of comments, never read at runtime)
2. Check if any code (bootstrap.py, config loading) explicitly references `config.yaml` as a fallback path and update if so
3. If `config.yaml` is referenced in docs or README as a template, update those references

### E3: Settings routes factory cleanup (post-Chunk 1)

**Context**: Chunk 1's A3 removes `apply_car_settings` and `apply_speed_source_settings` callback args. After Chunk 1, the factory will have 3 args: `settings_store`, `gps_monitor`, `analysis_settings`.

**Assessment**: 3 args is a reasonable factory signature. `gps_monitor` serving only 1 route is slightly wasteful but not worth splitting the router over. **No additional changes needed beyond what Chunk 1 delivers.**

**Steps**:
1. After Chunk 1 completes, verify the settings routes factory has 3 args
2. Close E3 as resolved — 3-arg factory is proportionate

## Dependencies on Other Chunks

- **E3** fully depends on Chunk 1's A3 (callback removal). After Chunk 1, E3 is resolved with no further work.
- **G2** import of `_hash_tree` requires that Chunk 3 hasn't deleted or relocated it from `update/status.py` (Chunk 3 touches update/ but not `_hash_tree`).
- **I3** and **H2** are independent and can be done in any order.

## Risks and Tradeoffs

1. **G2**: Importing from `vibesensor.update.status` in a build tool creates a dependency on the server package being installed. This is already the case for other dev tools. If this becomes an issue, the import can be made lazy.
2. **H2**: Removing config.yaml means `config.dev.yaml` becomes the effective base for development. If developers expected a template, they lose it. The dev config already has the right defaults.
3. **I3**: If a future uvicorn release changes its `[standard]` extras to drop uvloop, the app would lose it silently. This is unlikely and trivially fixable if it ever happens.

## Validation Steps

1. `pip install -e "./apps/server[dev]"` — verify install succeeds without uvloop direct dep
2. `python -c "import uvloop"` — verify it's still available via uvicorn[standard]
3. `python tools/build_ui_static.py --help` — verify simplified CLI
4. `cd apps/ui && npm ci && npm run build` — verify UI build still works
5. `make lint && make typecheck-backend`
6. `make test-all`

## Required Documentation Updates

- Remove any references to `config.yaml` as a template file in docs/README
- Update `docs/ai/repo-map.md` if it lists config.yaml

## Required AI Instruction Updates

- No new guardrails needed for this chunk — existing "no speculative config knobs" rule covers H2, and "single source of truth" covers G2.

## Simplification Crosswalk

### G2: build_ui_static.py caching
- **Validation**: Confirmed. Dual `_hash_tree()`, conflicting flags.
- **Root cause**: Build tool grew its own caching system independently from the production hash utility.
- **Steps**: Import production `_hash_tree`, remove flags.
- **Code areas**: tools/build_ui_static.py
- **Removed**: ~15 lines (local hash function + flag parsing)
- **Verification**: `python tools/build_ui_static.py --help`, UI build test

### I3: uvloop redundant dep
- **Validation**: Confirmed. Zero imports, transitive via uvicorn[standard].
- **Root cause**: Explicit dep added before recognizing it was already transitive.
- **Steps**: Remove from pyproject.toml.
- **Code areas**: apps/server/pyproject.toml (1 line)
- **Removed**: 1 redundant dependency declaration
- **Verification**: `pip install -e ".[dev]" && python -c "import uvloop"`

### H2: Empty config.yaml
- **Validation**: Confirmed. 6 lines of comments.
- **Root cause**: Placeholder template that was never populated.
- **Steps**: Delete file, update any references.
- **Code areas**: apps/server/config.yaml
- **Removed**: 1 empty file
- **Verification**: `make test-all`

### E3: Settings routes factory
- **Validation**: Confirmed. 5 args, 2 are callbacks.
- **Root cause**: Callbacks used as indirection for settings sync.
- **Steps**: Resolved by Chunk 1's A3. No additional work in this chunk.
- **Code areas**: None (handled by Chunk 1)
- **Removed**: N/A
- **Verification**: Visual inspection after Chunk 1

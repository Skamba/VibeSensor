# Chunk 5 Plan: Streamline Build, Tooling, and Test Infrastructure

## Mapped Findings

| ID | Original Finding | Source Subagents |
|----|-----------------|-----------------|
| W1 | run_ci_parallel.py 300+ lines reimplements CI logic | Workflow #1 |
| W2 | CI backend-quality 8 individual steps vs `make lint` | Workflow #2 |
| W3 | 5 overlapping test entry points | Workflow #3 |
| T1 | 29 omnibus regression files spanning 8+ modules | Testing #1 |
| T2 | scenario_ground_truth.py forwarding wrappers | Testing #2 |
| T3 | test_support import consistency — 3+ import styles | Testing #3 |
| L3 | [ocr] extras group — 0 production callers | Library #3 |

## Validation Summary

### W1: run_ci_parallel.py — CONFIRMED (refinement applied)

The script (`tools/tests/run_ci_parallel.py`, ~300 lines) defines 7 jobs that delegate to external commands. Key observations:
- Jobs delegate to `make lint`, `make typecheck-backend`, `pytest`, `npm ci && npm run typecheck`, etc.
- The script adds a threading orchestrator with colorized output, job-level parallelism, and selective job running (`--job` flag)
- It is **not** reimplementing lint/typecheck/test logic — it's a parallel runner
- The general instructions explicitly document this as the CI-parity suite: `make test-all` delegates to `python3 tools/tests/run_ci_parallel.py`
- **Value:** The parallel orchestration provides ~2-3x speedup for local CI runs

**Revised finding:** The script is not redundant. The finding should focus on sync maintenance burden: the script hardcodes 7 job definitions that must stay in sync with `.github/workflows/ci.yml`. A docstring states this obligation but there's no automated sync check.

### W2: CI backend-quality 8 Steps vs `make lint` — CONFIRMED

CI workflow `.github/workflows/ci.yml` `backend-quality` job runs 8 individual steps:
1. `ruff check apps/server/`
2. `ruff format --check apps/server/`
3. `python3 tools/dev/docs_lint.py`
4. `python3 tools/dev/loc_check.py`
5. `python3 tools/config/generate_contract_reference_doc.py --check`
6. `python3 tools/dev/check_hygiene.py .github/instructions/*.md docs/ai/repo-map.md`
7. `ruff check tools/ --config apps/server/pyproject.toml --select I`
8. (plus some setup steps)

`make lint` runs most of these in sequence. The delta is that CI ruff steps scope to `apps/server/` while `make lint` runs broader patterns. Minor but real divergence.

### W3: 5 Overlapping Test Entry Points — CONFIRMED

Makefile targets:
- `test`: `pytest -q apps/server/tests/`
- `test-all`: `python3 tools/tests/run_ci_parallel.py` (7 parallel jobs)
- `test-full-suite`: `python3 tools/tests/run_ci_parallel.py && python3 tools/tests/run_e2e_parallel.py`
- `coverage`: `pytest --cov=vibesensor ...`
- `smoke`: not in Makefile but in pyproject.toml test markers

`test-all` is documented in general.instructions.md as the CI-parity suite. `test` is the quick backend-only suite. `test-full-suite` adds e2e. These serve different purposes. `coverage` is a separate concern.

**Revised finding:** This is not fragmentation — these are distinct scopes. The naming is clear. The only issue is that `test-all` is described as "non-containerized" in general.instructions.md but runs `run_ci_parallel.py` which includes Docker e2e in `test-full-suite` (actually `test-all` does NOT include e2e — `test-full-suite` does). Documentation correction needed.

### T1: 29 Omnibus Regression Files — CONFIRMED

Tests under `apps/server/tests/` include large omnibus regression files spanning many modules. Specific examples:
- `tests/integration/test_multi_domain_regressions.py` — spans analysis, report, history, boundaries
- `tests/integration/test_real_world_scenarios.py` — spans analysis, persistence, report

These files grew organically as integration-level regression tests. Breaking them into feature-area directories would be a massive mechanical effort.

**Revised finding:** These are integration tests that intentionally span multiple modules. The issue is not their existence but that some test functions could be better organized. Full reorganization is out of scope for this simplification effort — too much mechanical churn for the benefit.

### T2: scenario_ground_truth.py Forwarding Wrappers — CONFIRMED

`tests/test_support/scenario_ground_truth.py` contains functions that wrap or forward to other test utilities. This creates indirection in test setup.

### T3: test_support Import Consistency — CONFIRMED

Tests import from `test_support` using at least 3 patterns:
- `from tests.test_support.X import Y`
- `from test_support.X import Y`
- Direct path manipulation in `_paths.py`

### L3: [ocr] Extras Group — CONFIRMED

`pyproject.toml` defines `[ocr]` extras: `pytesseract`, `Pillow`. Zero production callers. Only referenced in tests with `pytest.importorskip("pytesseract")`. Can be safely removed from production extras and kept as dev dependencies if tests need them.

## Simplification Strategy

### Step 1: Remove [ocr] Extras Group (L3)

1. In `apps/server/pyproject.toml`, remove the `[project.optional-dependencies].ocr` section
2. If `pytesseract`/`Pillow` are needed for test runs, add them to `[dev]` extras or keep them as test-only dependencies
3. Remove any code that references `vibesensor[ocr]` in install instructions or scripts
4. Tests using `importorskip("pytesseract")` continue to work — they skip gracefully when not installed

### Step 2: Simplify scenario_ground_truth.py Forwarding (T2)

1. Audit `tests/test_support/scenario_ground_truth.py` for forwarding functions that add no value
2. Replace pure forwarding calls with direct imports at call sites
3. Remove forwarding functions from `scenario_ground_truth.py`
4. If the module becomes empty/trivial after removal, delete it and update imports

### Step 3: Standardize test_support Imports (T3)

1. Pick one canonical import style: `from tests.test_support.X import Y` (full path, no ambiguity)
2. Search all test files for `from test_support` (without `tests.` prefix) and update to the canonical form
3. Verify `_paths.py` sys.path manipulation is still needed. If tests run fine without it (pytest handles path resolution), remove the path manipulation
4. This is a mechanical find-and-replace across test files

### Step 4: Add CI Job Sync Check (W1)

Rather than removing `run_ci_parallel.py` (which provides genuine value as a parallel runner), add a lightweight sync check:

1. Add a comment block at the top of `run_ci_parallel.py` listing the CI workflow jobs it mirrors
2. In `check_hygiene.py` (already runs in CI), add a check that the job names in `run_ci_parallel.py` match the job names in `.github/workflows/ci.yml`
3. This prevents silent drift without removing the useful parallel runner

### Step 5: Fix Documentation Inaccuracies (W2/W3)

1. In `general.instructions.md`, clarify that `make test-all` runs `run_ci_parallel.py` which mirrors CI jobs but does NOT include Docker e2e (that's `test-full-suite`)
2. Document the actual relationship between `make lint` and CI `backend-quality`:
   - `make lint` runs broader scope (includes `tools/` ruff check)
   - CI `backend-quality` matches `make lint` scope but individual steps give better error isolation
   - CI `backend-quality` is authoritative; `make lint` is the local convenience alias
3. Remove or update any misleading descriptions of entry points

### Step 6: T1 — Scoped Test Organization (Conservative)

Full reorganization of 29 regression files is out of scope (too much mechanical churn). Instead:

1. Document the intended test layout pattern in `docs/testing.md`
2. For any tests touched during Chunk 1-4 implementation that are in omnibus files, move them to the appropriate feature-area directory as part of those changes
3. Future test additions should follow the feature-area directory pattern
4. Add a brief note to `tests.instructions.md` discouraging new omnibus regression files

## Simplification Crosswalk

### W1: run_ci_parallel.py
- **Validation result:** CONFIRMED (refined — the script is a useful parallel runner, not reimplementation)
- **Root cause:** CI job definitions hardcoded in script with only docstring sync obligation
- **Steps:** Step 4
- **Areas:** `tools/tests/run_ci_parallel.py`, `tools/dev/check_hygiene.py`
- **Removed:** Silent drift risk (replaced with automated sync check)
- **Verification:** `make test-all` still works, hygiene check catches CI workflow changes

### W2: CI backend-quality vs make lint
- **Validation result:** CONFIRMED — minor scope divergence
- **Root cause:** CI steps and Makefile targets evolved independently
- **Steps:** Step 5
- **Areas:** `.github/instructions/general.instructions.md`
- **Removed:** Documentation confusion (not code — the divergence is intentional for different scopes)
- **Verification:** Documentation accurately reflects actual behavior

### W3: 5 Test Entry Points
- **Validation result:** CONFIRMED (revised — these serve distinct scopes, not truly overlapping)
- **Root cause:** Documentation describes them poorly
- **Steps:** Step 5
- **Areas:** `.github/instructions/general.instructions.md`
- **Removed:** Misleading documentation
- **Verification:** Entry point descriptions match actual behavior

### T1: 29 Omnibus Regression Files
- **Validation result:** CONFIRMED (revised — integration tests intentionally span modules)
- **Root cause:** Organic growth of integration tests without feature-area organization
- **Steps:** Step 6
- **Areas:** `docs/testing.md`, `.github/instructions/tests.instructions.md`
- **Removed:** Future accumulation of omnibus files (via documentation guardrails)
- **Verification:** New tests follow feature-area pattern

### T2: scenario_ground_truth.py Forwarding
- **Validation result:** CONFIRMED
- **Root cause:** Test helper evolution left forwarding wrappers
- **Steps:** Step 2
- **Areas:** `tests/test_support/scenario_ground_truth.py`, test files that use it
- **Removed:** Pure forwarding functions
- **Verification:** All affected tests pass with direct imports

### T3: test_support Import Consistency
- **Validation result:** CONFIRMED — 3+ import styles
- **Root cause:** No enforced convention
- **Steps:** Step 3
- **Areas:** `tests/_paths.py`, all test files importing from test_support
- **Removed:** Multiple import styles (standardized to one)
- **Verification:** All tests pass, imports consistent

### L3: [ocr] Extras Group
- **Validation result:** CONFIRMED — 0 production callers
- **Root cause:** Speculative feature never completed
- **Steps:** Step 1
- **Areas:** `apps/server/pyproject.toml`
- **Removed:** Dead optional dependency group
- **Verification:** `pip install -e "./apps/server[dev]"` succeeds, tests still skip OCR gracefully

## Dependencies

- **Independent of Chunks 1-4** — this chunk touches build/test infrastructure, not application code
- **Exception:** Step 6 (T1) suggests moving tests touched during Chunks 1-4, creating a soft dependency. This is advisory, not blocking.

## Risks and Tradeoffs

1. **Step 1 (OCR extras):** Zero risk — no production callers confirmed
2. **Step 2 (scenario_ground_truth):** Low risk — need to verify all forwarding sites before removing
3. **Step 3 (import style):** Low risk — mechanical find-and-replace, validated by running tests
4. **Step 4 (sync check):** Low risk — additive change only
5. **Step 5 (docs):** Zero risk — documentation only
6. **Step 6 (T1 scoping):** Zero risk — documentation only, actual moves happen in other chunks

## Required Documentation Updates
- Update `docs/testing.md` with test layout conventions
- Update `.github/instructions/general.instructions.md` with accurate entry point descriptions
- Update `.github/instructions/tests.instructions.md` with import style convention and anti-omnibus guidance

## Required AI Instruction Updates
- Add to `tests.instructions.md`: "Use `from tests.test_support.X import Y` as the canonical import style. Do not manipulate sys.path for test imports."
- Add to `tests.instructions.md`: "Place new regression tests in the appropriate feature-area directory under `tests/`, not in omnibus regression files."

## Required Test Updates
- All test files must pass after import style standardization
- scenario_ground_truth forwarding removal must be verified against all consumers

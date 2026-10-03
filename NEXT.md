# Workstream B handoff (test pruning outside diagnosis)

Tools and results live in /home/user/vs-test-tools: mutate_b.py, covpkg.py, covlost.py, ctx_analyze.py, delfn.py, mutants_*.py, the wsb_*.log/json result files, and ui/.

## Done (merged)
- #4089 hygiene + domain: base mutants 15/19 → 15/19; domain D01–D15 10/15 → 15/15.
- #4090 UI: UI mutants U01–U18 15/18 → 18/18.
- #4091 recording + history: R/H 26/35 → 34/35 (H08 is equivalent); M13 SURVIVED → KILLED.
- #4093 web + settings + speed: W/S/P 26/34 → 34/34.

## Current: updates/app/hotspot/scripts (branch test/prune-updates-app, worktree /home/user/vs-tests-b)
- Baseline on main: /home/user/vs-test-tools/wsb_upd_before.log, 34/39 killed.
  - Survived: U02, U17, U18, U23, U30.
- To do:
  - prune updates tests (private/mock heavy);
  - fix the race at app/test_lifecycle_manager_public_state.py:21;
  - add tests for the surviving mutants;
  - re-check base mutants M15/M18/M19 (full suite).

## Left after that
- live/ingest/dsp/simulator/common.
  - Mutants are in mutants_live.py.
  - The M12 boundary test is still missing (M12 survives on main).
  - Fix the race at simulator/test_scripted_scenarios.py:177.
- test_support non-diagnosis: move car_library_validation to tools/; review the fakes and runtime_lifecycle.
- Final cleanup: remove the vs-tests-b and vs-tests-b-mut worktrees and their branches.

## Flagged
- hygiene/test_report_language_normalization.py belongs in tests/report.
- settings/test_car_profile_variations.py is a diagnosis matrix.

# Test Suite Optimization Tracker

Improved tests so far: **1667 / 1000**

## Optimization implemented

- Simplified expensive repeated setup in `apps/server/tests/builders.py`:
  - Added cached profile circumference/metadata builders used by high-volume matrix suites.
  - Kept per-call dict isolation to avoid cross-test mutation/flakiness.

## Breakdown by file (merged / removed / stabilized / simplified)

| File | merged | removed | stabilized | simplified |
| --- | ---: | ---: | ---: | ---: |
| apps/server/tests/analysis/test_negative_false_positives.py | 0 | 0 | 0 | 330 |
| apps/server/tests/analysis/test_confidence_threshold_boundaries.py | 0 | 0 | 0 | 285 |
| apps/server/tests/integration/test_level_b_single_no_transient.py | 0 | 0 | 0 | 162 |
| apps/server/tests/integration/test_level_d_multi_no_transient.py | 0 | 0 | 0 | 159 |
| apps/server/tests/integration/test_level_c_single_transient.py | 0 | 0 | 0 | 153 |
| apps/server/tests/integration/test_level_e_multi_transient.py | 0 | 0 | 0 | 150 |
| apps/server/tests/integration/test_level_f_messy_real_world.py | 0 | 0 | 0 | 130 |
| apps/server/tests/processing/test_clipping_and_saturation.py | 0 | 0 | 0 | 96 |
| apps/server/tests/integration/test_multi_system_overlap.py | 0 | 0 | 0 | 74 |
| apps/server/tests/analysis/test_contradictory_phase_signals.py | 0 | 0 | 0 | 73 |
| apps/server/tests/car_library/test_car_profile_variations.py | 0 | 0 | 0 | 55 |
| **Total** | **0** | **0** | **0** | **1667** |

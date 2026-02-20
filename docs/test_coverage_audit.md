# Test Coverage Audit

> Generated: 2026-02-20
> Baseline: 481 tests passed, 8 selenium deselected
> After audit: 527 tests passed, 8 selenium deselected

---

## Test Suite Overview

| Area | Location | Runner | Count |
|------|----------|--------|-------|
| Server unit tests | `apps/server/tests/` | pytest, `-m "not selenium"` | 527 |
| Selenium UI tests | `apps/server/tests/test_ui_selenium.py` | pytest, `-m selenium` | 8 |
| Docker E2E tests | `apps/server/tests_e2e/` | pytest via `tools/tests/run_full_suite.py` | 2 suites |
| UI build checks | `apps/ui/` | npm run build, npm run typecheck | — |
| Lint/format | Makefile | ruff check + ruff format | — |

### Markers

| Marker | Purpose |
|--------|---------|
| `selenium` | Browser-based UI tests (skipped in CI) |
| `e2e` | Docker-based end-to-end tests |
| `long_sim` | Longer simulated-run tests (>20s) |
| `smoke` | Minimal critical path checks |

---

## Accuracy Review Summary

### Tests Fixed

| File | Issue | Fix |
|------|-------|-----|
| `test_ui_selenium.py` | All 7 tests referenced stale DOM selectors from old 4-tab UI (tab-logs, tab-report, logsView, etc.) | Updated all selectors to match current 3-tab UI (tab-history, historyView, etc.). Added `_activate_settings_subtab()` helper. Updated all i18n assertions. |

### Tests Already Correct (Notable)

- **test_car_library.py** — Extremely thorough data validation with field presence, bounds, and cross-field consistency
- **test_common_vibration_causes.py** — Well-designed parametrized physics tests with independent manual calculations
- **test_strength_single_source_guards.py** — AST-based guards preventing duplicate log10 implementations
- **test_single_source_of_truth.py** — Cross-module identity checks, dead-alias enforcement, cross-language constant verification
- **test_hotspot_self_heal.py** — Excellent fake-runner pattern with comprehensive scenario coverage
- **test_protocol.py** — Comprehensive roundtrip tests, error paths, and constant validation

---

## User Journeys Inferred from Code

| # | Journey | Description |
|---|---------|-------------|
| 1 | Sensor connection | ESP sensor sends UDP HELLO → appears in /api/clients |
| 2 | UDP data reception | DATA packets → queue → parse → ingest into SignalProcessor |
| 3 | Start recording | POST /api/logging/start → HistoryDB creates run → live diagnostics reset |
| 4 | Live WebSocket data | Processing loop → build_ws_payload → WS broadcast → UI renders |
| 5 | Stop run + analysis | POST /api/logging/stop → finalize → post-analysis → status=complete |
| 6 | Report generation | Analysis data → summarize_log → build_report_pdf → PDF |
| 7 | History listing | GET /api/history → list of runs with metadata |
| 8 | Run deletion | DELETE /api/history/{id} → cascade delete, 409 if active |
| 9 | Car profile CRUD | Add/update/delete cars, set active, propagate to analysis |
| 10 | Sensor name/location | POST /api/clients/{id}/location → uniqueness enforced (409) |
| 11 | Speed source | Manual override vs GPS, propagate to recording |
| 12 | Export/download | GET /api/history/{id}/export → ZIP with JSON + CSV |
| 13 | GPS speed | GPSSpeedMonitor.run() → gpsd → speed_mps, reconnect |
| 14 | Health check | GET /api/health → status, processing_state, failures |
| 15 | Config validation | YAML loading, deep merge, path resolution, validation |
| 16 | Language/i18n | EN/NL switching in insights, PDF, and UI |

---

## Coverage Matrix

| Journey | Unit Tests | Integration | E2E Docker | Overall | Notes |
|---------|-----------|-------------|------------|---------|-------|
| 1. Sensor connection | ✅ | — | ✅ | **FULL** | |
| 2. UDP data reception | ✅ | — | ✅ | **FULL** | |
| 3. Start recording | ✅ | — | ✅ | **FULL** | |
| 4. Live WS data | ✅ hub | ❌ payload | — | **PARTIAL** | `build_ws_payload` untested |
| 5. Stop + analysis | ✅ DB | — | ✅ | **FULL** | |
| 6. Report generation | ✅ | ✅ | ✅ | **FULL** | Added section heading tests |
| 7. History listing | ✅ | ✅ | ✅ | **FULL** | |
| 8. Run deletion | ✅ | ✅ (new) | ✅ | **FULL** | Added 409 guard test, cascade test |
| 9. Car profile CRUD | ✅ | — | ✅ | **FULL** | |
| 10. Sensor name/location | ✅ | — | ✅ | **FULL** | |
| 11. Speed source | ✅ | — | ✅ | **FULL** | |
| 12. Export/download | ✅ | ✅ | ✅ | **FULL** | |
| 13. GPS speed | ✅ sync | — | — | **PARTIAL** | Async run() loop untested |
| 14. Health check | ✅ (new) | — | — | **FULL** | Added response shape test |
| 15. Config validation | ✅ | — | — | **FULL** | |
| 16. Language/i18n | ✅ (new) | ✅ | ✅ | **FULL** | Added key completeness tests |

---

## Tests Added in This Audit

### New test file: `test_vibration_math_coverage.py` (11 tests)

| Test | What it validates |
|------|-------------------|
| `test_bucket_exact_boundaries` (13 params) | Exact ±0.001 at every strength band boundary |
| `test_strength_db_exact_known_value` | dB formula against hand-calculated expected value |
| `test_strength_db_both_zero` | Zero band + zero floor ≈ 0 dB |
| `test_strength_db_negative_inputs_clamped` | Negative inputs clamped to zero |
| `test_combined_spectrum_three_axes_known_values` | RSS formula with known 3-axis input |
| `test_combined_spectrum_empty` | Empty input → empty output |
| `test_combined_spectrum_single_axis` | Single axis → values unchanged |
| `test_compute_strength_empty_input` | Empty spectrum → 0 dB, None bucket |
| `test_compute_strength_single_tone_produces_correct_peak` | Synthetic 25Hz tone → correct peak detection |

### New test file: `test_report_content_coverage.py` (8 tests)

| Test | What it validates |
|------|-------------------|
| `test_select_top_causes_groups_by_source` | Findings with same source grouped |
| `test_select_top_causes_empty_findings` | Empty input → empty output |
| `test_select_top_causes_excludes_reference_findings` | REF_* findings never in top causes |
| `test_confidence_label_boundaries` (6 params) | Exact bucket boundaries for high/medium/low |
| `test_pdf_section_headings_present` | All EN section headings in generated PDF |
| `test_pdf_nl_contains_dutch_headings` | All NL section headings in generated PDF |

### Added to `test_report_i18n.py` (3 tests)

| Test | What it validates |
|------|-------------------|
| `test_all_json_keys_have_en_and_nl` | Every i18n key has both EN and NL values |
| `test_all_source_referenced_keys_exist_in_json` | All tr() keys in source exist in JSON |
| `test_variants_returns_both_languages` | variants() returns both translations |

### Added to `test_history_db.py` (6 tests)

| Test | What it validates |
|------|-------------------|
| `test_future_schema_version_raises` | Version 99 → RuntimeError |
| `test_delete_run_cascades_samples` | DELETE CASCADE on samples |
| `test_run_status_transitions` | recording → analyzing → complete + error path |
| `test_append_empty_samples_is_noop` | Empty append doesn't change count |
| `test_client_names_crud` | upsert, list, delete client names |
| `test_settings_kv_roundtrip` | set/get settings with various JSON types |

### Added to `test_settings_store.py` (2 tests)

| Test | What it validates |
|------|-------------------|
| `test_store_corrupted_snapshot_falls_back_to_defaults` | Invalid DB data → safe defaults |
| `test_store_snapshot_with_empty_cars_falls_back` | Empty cars list → default car |

### Added to `test_runlog.py` (1 test)

| Test | What it validates |
|------|-------------------|
| `test_normalize_sample_record_strength_db_backward_compat` | `strength_db` → `vibration_strength_db` rename |

### Added to `test_health_endpoint.py` (1 test)

| Test | What it validates |
|------|-------------------|
| `test_health_endpoint_response_shape` | Response contains status, processing_state, processing_failures |

### Added to `test_api_history_endpoints.py` (1 test)

| Test | What it validates |
|------|-------------------|
| `test_delete_active_run_returns_409` | Cannot delete active recording run |

### Fixed in `test_ui_selenium.py` (7 tests + 1 helper updated)

All 7 existing tests updated for 3-tab UI restructure. Added `_activate_settings_subtab()` helper.

---

## Remaining Gaps (Lower Priority)

| Gap | Priority | Reason not addressed |
|-----|----------|---------------------|
| `build_ws_payload` shape test | P2 | Requires RuntimeState construction; heavy fixture |
| `GPSSpeedMonitor.run()` async loop | P2 | Requires mock TCP server |
| `MetricsLogger` full lifecycle integration | P2 | Complex async pipeline; covered by E2E |
| PDF chart/plot rendering verification | P2 | Image-based; would need visual regression tooling |
| Car wizard browser flow | P2 | Selenium-only; gated behind marker |
| WebSocket reconnection/stale detection | P2 | Browser-only; gated behind selenium marker |

---

## Risk Assessment

### What can break without being caught

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `build_ws_payload` produces wrong shape | Low | High (UI broken) | E2E Docker tests cover indirectly |
| GPS reconnect loop fails | Low | Medium (no speed data) | Config fallback to manual speed |
| PDF chart rendering regression | Low | Low (content still correct) | Section heading tests catch structural issues |
| i18n key added to code but not JSON | **Medium** | Medium (crash on translate) | **NEW** regression test catches this |
| Strength bucket boundary change | **Medium** | High (wrong severity) | **NEW** exact boundary tests catch this |
| Schema migration regression | Low | High (DB unusable) | **NEW** v1→v2→v3 + future version tests |

---

## Proposed Future Improvements

1. **Add `build_ws_payload` unit test** — Mock minimal RuntimeState, verify payload structure
2. **Add visual regression for PDF** — Snapshot first page as PNG, compare with tolerance
3. **Enable selenium in CI** — Currently skipped; would catch UI regressions
4. **Add libs/core independent test directory** — Core math tests currently live in apps/server/tests
5. **Add property-based tests for strength math** — Use hypothesis for exhaustive boundary testing

# Changelog

## Unreleased — Maintainability Audit

### Breaking changes (no backwards compatibility required)

- **Removed `strength_scoring.py`** — Legacy wrapper module deleted. Import
  directly from `vibesensor.analysis.strength_metrics` instead.
- **Removed `metrics_csv_path` config key** — Use `metrics_log_path` in
  `logging:` section of config YAML. The `LoggingConfig.metrics_csv_path`
  property alias is also removed.
- **Removed legacy log field aliases** — `accel_magnitude_rms_g`,
  `accel_magnitude_p2p_g`, `dominant_peak_amp_g`, and `noise_floor_amp` are no
  longer written to new metrics log records. The canonical names are
  `vib_mag_rms_g`, `vib_mag_p2p_g`, `strength_peak_band_rms_amp_g`, and
  `noise_floor_amp_p20_g`.
- **Removed `"combined"` alias from spectrum payloads** — WebSocket and API
  spectrum payloads no longer include the redundant `combined` field. Use
  `combined_spectrum_amp_g` instead.
- **UI no longer derives band defaults client-side** —
  `buildRecommendedBandDefaults()`, `treadWearModel`, and
  `bandToleranceModelVersion` removed from the UI. The UI now fetches canonical
  analysis settings from `GET /api/analysis-settings` on startup.

### Improvements

- **Single source of truth for analysis defaults** —
  `DEFAULT_DIAGNOSTIC_SETTINGS` is now an alias of `DEFAULT_ANALYSIS_SETTINGS`
  from `analysis_settings.py`, eliminating a duplicated 14-field dictionary.
- **Deduplicated `_as_float` / `as_float_or_none`** — Three identical
  float-conversion helpers consolidated into the canonical `as_float_or_none` in
  `runlog.py`. Both `diagnostics_shared._as_float` and
  `report_analysis._as_float` now import from `runlog`. This also fixes a
  correctness issue where the old `_as_float` did not reject `±Infinity`.
- **Deduplicated `_percentile`** — Two identical percentile implementations
  consolidated into the canonical `_percentile` in
  `analysis/strength_metrics.py`. `report_analysis` now imports it.
- **Removed dead `MetricsLogger._dominant_peak`** — Unused static method and its
  6 tests deleted (dead since the strength_metrics refactor).
- **Removed dead `peak_amp` / `floor_amp` aliases** — `compute_strength_metrics`
  no longer returns these redundant aliases that were never consumed.
- **Simplified config files** — `config.dev.yaml` and `config.docker.yaml` now
  contain only the fields that differ from the built-in defaults (path
  overrides), reducing duplication from ~40 lines each to ~6 lines.
- **All ruff lint and format issues resolved** — Zero remaining E501, F841, and
  I001 violations across `pi/vibesensor`, `pi/tests`, and `tools/simulator`.
- **CI lint step now fails the build** — Removed `continue-on-error: true` from
  the ruff lint step so formatting/style regressions block the pipeline.
- **Added logging to silent exception handlers** — `registry.py`,
  `gps_speed.py`, and `api.py` WebSocket handler now log when exceptions occur
  instead of silently swallowing them.
- **New guardrail tests** — `test_single_source_of_truth.py` prevents
  regression of the consolidation work with 9 focused assertions covering
  float converter identity, percentile identity, and dead-alias detection.
- **Added `GET /api/analysis-settings`** client-side API function for fetching
  server-canonical defaults.

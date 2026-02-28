# Metrics-to-Report Mapping

This document describes how every report field and visual element maps back
to a specific persisted analysis metric/value.  The report renderer
(`vibesensor.report.pdf_builder`) must **never** recompute or infer analysis
values; it reads exclusively from `ReportTemplateData` (built by
`vibesensor.analysis.report_data_builder.map_summary()`).

## Data flow

```
analysis.summarize_run_data(meta, samples)
  → summary dict (persisted in history_db)
    → analysis.map_summary(summary)
      → ReportTemplateData (embedded as summary["_report_template_data"])
        → report.pdf_builder.build_report_pdf(ReportTemplateData)
          → PDF bytes
```

## Page 1 — Diagnostic Worksheet

### Header panel

| Report field         | ReportTemplateData field     | Analysis source key                | Unit / format            |
|----------------------|------------------------------|------------------------------------|--------------------------|
| Title                | `title`                      | i18n `DIAGNOSTIC_WORKSHEET`        | string                   |
| Run date             | `run_datetime`               | `summary.report_date`              | `YYYY-MM-DD HH:MM:SS`   |
| Car                  | `car.name`, `car.car_type`   | `metadata.car_name` (fallback: `vehicle_name`), `metadata.car_type` (fallback: `vehicle_type`) | string |
| Start time UTC       | `start_time_utc`             | `summary.start_time_utc`           | ISO 8601 string          |
| End time UTC         | `end_time_utc`               | `summary.end_time_utc`             | ISO 8601 string          |
| Run ID               | `run_id`                     | `summary.run_id`                   | string                   |
| Duration             | `duration_text`              | `summary.record_length`            | human string             |
| Sensors              | `sensor_count`, `sensor_locations` | `summary.sensor_count_used`, `summary.sensor_locations` | int, list[str] |
| Sensor model         | `sensor_model`               | `summary.sensor_model`             | string                   |
| Firmware version     | `firmware_version`           | `summary.firmware_version`         | string                   |
| Sample count         | `sample_count`               | `summary.rows`                     | int                      |
| Sample rate          | `sample_rate_hz`             | `summary.raw_sample_rate_hz`       | `{:g}` Hz               |
| Tire size            | `tire_spec_text`             | `metadata.tire_width_mm/tire_aspect_pct/rim_in` | `{w:g}/{a:g}R{r:g}` |

### Observed Signature panel

| Report field             | ReportTemplateData field                        | Analysis source                             | Unit / format                |
|--------------------------|-------------------------------------------------|---------------------------------------------|------------------------------|
| Primary system           | `observed.primary_system`                       | `top_causes[0].source` → `_human_source()`  | i18n string                  |
| Strongest sensor         | `observed.strongest_sensor_location`            | `most_likely_origin.location` or `top_causes[0].strongest_location` | string |
| Speed band               | `observed.speed_band`                           | `top_causes[0].strongest_speed_band`         | string (e.g. "80–100 km/h") |
| Strength                 | `observed.strength_label`, `observed.strength_peak_amp_g` | `_top_strength_values()` → `strength_text()` | `"{Label} ({db:.1f} dB · {g:.3f} g peak)"` |
| Certainty                | `observed.certainty_label`, `observed.certainty_pct` | `certainty_label(conf)` | `"{Label} ({pct}%)"` |
| Certainty reason         | `observed.certainty_reason`                     | `certainty_label()` reason output            | string                       |
| Tier indicator           | `certainty_tier_key`                            | `certainty_tier(conf)` → `"A"`, `"B"`, `"C"` | single char               |

### Systems with Findings panel

| Report field          | ReportTemplateData field              | Analysis source                           | Unit / format          |
|-----------------------|---------------------------------------|-------------------------------------------|------------------------|
| System name           | `system_cards[].system_name`          | `top_causes[].source` → `_human_source()` | i18n string            |
| Strongest location    | `system_cards[].strongest_location`   | `top_causes[].strongest_location`         | string                 |
| Pattern summary       | `system_cards[].pattern_summary`      | `top_causes[].signatures_observed[:3]`    | comma-separated string |
| Parts list            | `system_cards[].parts`                | `parts_for_pattern()` (Tier C only)       | list[PartSuggestion]   |
| Tone                  | `system_cards[].tone`                 | `top_causes[].confidence_tone`            | "success"/"warn"/"neutral" |

**Tier gating:**
- Tier A: no system cards shown (replaced with guidance message)
- Tier B: system cards shown but parts list cleared, system name suffixed with hypothesis label
- Tier C: full system cards with parts

### Next Steps panel

| Report field     | ReportTemplateData field         | Analysis source              | Unit / format  |
|------------------|----------------------------------|------------------------------|----------------|
| Action           | `next_steps[].action`            | `test_plan[].what` (Tier B/C) or i18n guidance (Tier A) | string |
| Why              | `next_steps[].why`               | `test_plan[].why`            | string         |
| Speed band       | `next_steps[].speed_band`        | `test_plan[].speed_band`     | string         |
| Rank             | `next_steps[].rank`              | enumeration index            | int            |

**Tier gating:**
- Tier A: data-collection guidance steps only
- Tier B/C: test-plan steps from analysis

### Data Trust panel

| Report field | ReportTemplateData field       | Analysis source              | Unit / format       |
|--------------|--------------------------------|------------------------------|---------------------|
| Check        | `data_trust[].check`           | `run_suitability[].check`    | i18n string         |
| State        | `data_trust[].state`           | `run_suitability[].state`    | "pass" / "warn"     |
| Detail       | `data_trust[].detail`          | `run_suitability[].explanation` | string or None   |

## Page 2 — Evidence & Diagnostics

### Car Visual / Location Hotspots

| Report field       | ReportTemplateData field          | Analysis source                              | Unit / format |
|--------------------|-----------------------------------|----------------------------------------------|---------------|
| Location rows      | `location_hotspot_rows`           | Pre-computed from `findings[].matched_points` or `sensor_intensity_by_location` | list[dict] |
| Hotspot unit       | `location_hotspot_rows[].unit`    | `"g"` (from matched_points) or `"db"` (from sensor_intensity) | string |
| Peak value         | `location_hotspot_rows[].peak_value` | max amplitude at location                 | float         |
| Mean value         | `location_hotspot_rows[].mean_value` | mean amplitude at location                | float         |

### Pattern Evidence panel

| Report field         | ReportTemplateData field                        | Analysis source                        | Unit / format |
|----------------------|-------------------------------------------------|----------------------------------------|---------------|
| Matched systems      | `pattern_evidence.matched_systems`              | `top_causes[:3].source` → `_human_source()` | list[str] |
| Strongest location   | `pattern_evidence.strongest_location`           | Same as `observed.strongest_sensor_location` | string |
| Speed band           | `pattern_evidence.speed_band`                   | Same as `observed.speed_band`          | string        |
| Strength             | `pattern_evidence.strength_label`, `.strength_peak_amp_g` | Same as `observed.strength_*` | same format |
| Certainty            | `pattern_evidence.certainty_label`, `.certainty_pct` | Same as `observed.certainty_*` | same format |
| Certainty reason     | `pattern_evidence.certainty_reason`             | Same as `observed.certainty_reason`    | string        |
| Warning              | `pattern_evidence.warning`                      | `certainty_reason` if `weak_spatial_separation` | string or None |
| Interpretation       | `pattern_evidence.interpretation`               | `most_likely_origin.explanation`       | string        |
| Why parts listed     | `pattern_evidence.why_parts_text`               | `why_parts_listed()`                   | string        |

### Diagnostic Peaks table

| Report field    | ReportTemplateData field   | Analysis source                      | Unit / format         |
|-----------------|----------------------------|--------------------------------------|-----------------------|
| Rank            | `peak_rows[].rank`         | `plots.peaks_table[].rank`           | int → string          |
| System          | `peak_rows[].system`       | Inferred from `source`/`order_label` | i18n string           |
| Frequency       | `peak_rows[].freq_hz`      | `plots.peaks_table[].frequency_hz`   | `{:.1f}` Hz           |
| Order           | `peak_rows[].order`        | `plots.peaks_table[].order_label`    | string                |
| Amplitude       | `peak_rows[].amp_g`        | `plots.peaks_table[].p95_amp_g`      | `{:.4f}` g            |
| Strength (dB)   | `peak_rows[].strength_db`  | `plots.peaks_table[].strength_db`    | `{:.1f}` dB           |
| Speed band      | `peak_rows[].speed_band`   | `plots.peaks_table[].typical_speed_band` | string            |
| Relevance       | `peak_rows[].relevance`    | Composed from `peak_classification`, `presence_ratio`, `persistence_score` | `"{class} · {pres:.0%} PRESENCE · SCORE {score:.2f}"` |

## Cross-section consistency rules

1. **Observed ↔ Pattern Evidence**: `strength_label`, `strength_peak_amp_g`,
   `certainty_label`, `certainty_pct`, `certainty_reason`, `strongest_sensor_location`,
   and `speed_band` must be identical between `observed` and `pattern_evidence`.

2. **Tier gating**: `certainty_tier_key` controls which sections are shown/suppressed.
   The tier is derived from the same confidence value used for `certainty_label`.

3. **Units**: Strength is always in dB (formatted `{:.1f}`), amplitude in g
   (formatted `{:.4f}` in peaks, `{:.3f}` in observed), frequency in Hz (`{:.1f}`).

4. **Location hotspot unit**: Either "g" (from matched_points) or "db" (from
   sensor_intensity fallback). Both paths are valid but must not be mixed within
   a single report.

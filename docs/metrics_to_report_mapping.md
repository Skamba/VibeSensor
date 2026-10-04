# Metrics-to-Report Mapping

Every value in the PDF comes from the stored analysis summary (`AnalysisSummary`)
or the run metadata (`RunMetadata`). `report/view_model.py` only formats and
translates; it never recomputes analysis values. Most values come from the
summary's `diagnosis` block (`d` below; contract in
`summary/diagnosis_contracts.py`).

## Page 1 (owner)

| Report element | Source | Format |
|---|---|---|
| Car, tires, date | `metadata.car` name and type, `metadata.analysis_settings` tire size, `start_time_utc` + `recorded_utc_offset_seconds` | `225/45R17`; local time with UTC offset |
| Speeds driven, duration, sensors | `speed_stats.min_kmh`/`max_kmh`, `duration_s`, `sensor_count_used` | `50–118 km/h`, `m:ss` |
| Verdict headline | `d.verdict`, `d.source`, `d.zone` | "Likely cause: …", "Not enough evidence to name a cause", or "No significant vibration found" |
| Confidence | `d.confidence_level` | Level word + action meaning; never a percentage |
| Plain description | `d.order_code`, `d.frequency_hz`, `d.reference_speed_kmh`, the top two `d.location_amplitudes` (ratio), `d.speed_min_kmh`/`speed_max_kmh`, `d.speed_dependence` | One sentence, plus "It follows road/engine speed: …" after a guided coast-down |
| Weak reasons | `d.weak_reasons` (`intermittent`: `d.presence_ratio`, the share of the moving drive in which the order was there, is under half) | Plain sentences, no percentages |
| Covered / not covered (no fault) | `speed_stats`, `phase_info.phase_pcts`, `d.location_amplitudes` locations, `d.conditions.rpm_source` | Sentences |
| Next step, fallback, cheap check | `d.order_code`, `d.source`, `d.zone`, `d.confidence_level` (Moderate adds the cheap check), `d.speed_dependence` (a done coast-down replaces the neutral check) | Fixed texts per order or source; a wheel fault on all four wheels gets the neutral coast check instead of an axle swap; a wheel/tire fault whose zone is not a wheel (cabin-only sensors) names no wheel and asks for a sensor at each wheel |
| Check the fix | `d.order_code`, strongest `d.location_amplitudes[0].amplitude_mg` | Re-run instruction + today's level |
| Car diagram | `d.location_amplitudes` (ratio → dot size), `d.zone` | Corner, axle (wheel/tire: two corners of that axle near the top), engine bay, or centre tunnel |

## Page 2 (workshop)

| Report element | Source | Format |
|---|---|---|
| Test conditions | `d.conditions` (speed source, RPM source, tire circumference, ratios), `phase_info.phase_pcts`, `d.guided_phases`, `sensor_locations` | Facts grid; speed source as GPS, OBD, entered by hand, or entered by hand as the fallback (unknown slugs read "unknown") |
| Findings table | `d.order_findings[]` | `T1 - once per wheel turn`, `12.1 Hz @ 85 km/h`, km/h range, phases, presence %, location, level (the diagnosed row carries `d.confidence_level`, Weak when the coast-down contradicts it) |
| Amplitude per location | `d.location_amplitudes[]` | `250 mg (34 dB)`, ratio `1.0x`; "not detected" when absent |
| Spectrum | `d.spectrum` (recurring peaks in mg over the moving samples, floor, order markers at the window speed; E1/E2 from the median measured RPM when RPM was measured) | Stems + dashed floor + order lines |
| Amplitude vs speed | `d.amplitude_vs_speed` | Lines per location; shown only for a ≥ 30 km/h sweep |
| Ruled out / not testable | `d.source_checks[]` | `Engine: not testable: no RPM or gear ratio`; `Engine: ruled out: the vibration kept going while coasting in neutral` |
| Shop request | `d.verdict`, `d.source`, `d.order_code` | Tire (road force, match-mount, runout), driveline, engine, or other |

## Data quality (page 3 or footer)

| Report element | Source |
|---|---|
| Checks | `run_suitability[]` (`check_key` label, `state`, plain meaning; a warning keeps its measured specifics) |
| Warnings | `warnings[].code` → plain text, else the resolved `title` |
| Traceability | `run_id`, `sensor_model`, `firmware_version`, `raw_sample_rate_hz`, VibeSensor version |

## Units

- **Strength:** dB everywhere. In the diagnosis block, amplitude at the
  diagnosed order is in mg, always shown next to its dB above floor (see
  `docs/metrics.md`).
- **Frequency:** Hz, one decimal.
- **Speed:** km/h, integers.
- **Format:** Dutch uses a decimal comma.

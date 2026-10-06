# Metrics-to-Report Mapping

Every value in the PDF comes from the stored analysis summary (`AnalysisSummary`)
or the run metadata (`RunMetadata`). `report/view_model.py` only formats and
translates; it never recomputes analysis values. Most values come from the
summary's `diagnosis` block (`d` below; contract in
`summary/diagnosis_contracts.py`).

## Page 1 (owner)

| Report element | Source | Format |
|---|---|---|
| Car, tires, date | `metadata.car` name and type, `metadata.analysis_settings` tire size, `start_time_utc` in the browser-reported time zone, else with `recorded_utc_offset_seconds`; "not verified (the Pi clock was not set)" when `metadata.start_time_unverified` (also for runs from older releases or an earlier boot, which can never be corrected) | `225/45R17`; local time with UTC offset |
| Speeds driven, duration, sensors | `speed_stats.min_kmh`/`max_kmh`, `duration_s`, `sensor_count_used` | `50–118 km/h`, `m:ss` |
| Verdict headline | `d.verdict`, `d.source`, `d.zone` | "Likely cause: …", "Not enough evidence to name a cause", "Vibration found, but no checked cause explains it" (`no_fault` with `d.unexplained_vibration`), or "No significant vibration found"; brakes read "brake judder from the brake discs on the front/rear axle" (unlocated: "felt strongest at …") |
| Confidence | `d.confidence_level` | Level word + action meaning; never a percentage |
| Plain description | `d.order_code`, `d.frequency_hz`, `d.reference_speed_kmh`, the top two `d.location_amplitudes` (ratio), `d.speed_min_kmh`/`speed_max_kmh`, `d.speed_dependence` | One sentence, plus "It follows road/engine speed: …" after a guided coast-down, or "only while braking" for brakes |
| Weak reasons | `d.weak_reasons` (`intermittent`: `d.presence_ratio`, the share of the moving drive in which the order was there, is under half) | Plain sentences, no percentages |
| No-fault sentence | `d.source_checks[]` | "Nothing stood out in the checks this run could make: wheels/tires, driveline and engine (top gear only)." plus "Not checked, so not shown to be fine: …" for `not_testable` sources; a run that could check nothing says so |
| Covered / not covered (no fault) | Covered: `speed_stats`, `phase_info.phase_pcts`, `d.location_amplitudes` locations. Not covered: `d.source_checks[]` (`not_testable` and `ruled_out_estimated`, each with its fix; brakes `no_braking` asks for a few firm stops from about 100 km/h, because coasting does not count, and an EV's or PHEV's `regen_braking` for the guided test's firm stops with regeneration at its lowest, or firm stops on the brake pedal, harder than regeneration alone; History names that speed in the display unit), then `speed_stats` and `phase_info.phase_pcts` gaps ("coasting" when the drive had neither a `deceleration` nor a `coast_down` phase; braking does not count as coasting) | Sentence; bullet list |
| Next step, fallback, cheap check | `d.order_code`, `d.source`, `d.zone`, `d.confidence_level` (Moderate adds the cheap check), `d.speed_dependence` (a done coast-down replaces the neutral check) | Fixed texts per order or source; a wheel fault on all four wheels gets the neutral coast check instead of an axle swap; a wheel/tire fault whose zone is not a wheel (cabin-only sensors) names no wheel and asks for a sensor at each wheel; brakes name the front or rear brake discs and the cheap check is a few firm stops from about 100 km/h (steering wheel: front discs; seat and pedal: rear discs) |
| Check the fix | `d.order_code`, strongest `d.location_amplitudes[0].amplitude_mg` | Re-run instruction + today's level |
| Car diagram | `d.location_amplitudes` (ratio → dot size), `d.zone` | Corner, axle (wheel/tire: two corners of that axle near the top), engine bay, or centre tunnel |
| Drive-layout wording | `d.driveline_parts` (`front_drive`, `propshaft_rear`, likelier first), `d.conditions.drive_layout` / `propshaft` | A driveline fault's cause, next step and fallback name the gearbox output shaft, final-drive pinion and differential bearings (`front_drive` alone: the parts turning at wheel speed x final drive; never drive shafts or CV joints, which turn at wheel speed), the propshaft and its joints (`propshaft_rear`, today's wording), or both in order (AWD, where `front_drive` reads as the front propshaft and front differential pinion). A car without a propshaft (`propshaft` false) never reads "propshaft": P1/P2 are "per gearbox output-shaft turn", and the ruled-out line, empty worksheet and narrow-speed reason say "gearbox output shaft". Without a layout (`drive_layout` null or absent) the propshaft step gets "The car's drive layout was not given: on a front-wheel-drive car … the gearbox output shaft, the final-drive pinion and the differential bearings" appended |
| EV wording | `d.conditions.fuel_type` `EV` | The driveline source reads "Electric motor" (P1/P2 are once/twice per motor revolution), a driveline zone no axle dominates reads "the drive unit", the engine reads "not applicable", and the cheap check is a repeat drive instead of a neutral coast |

## Page 2 (workshop)

| Report element | Source | Format |
|---|---|---|
| Test conditions | `d.conditions` (speed source, RPM source, tire circumference, final drive and top gear with `tire_provenance` / `final_drive_provenance` / `gear_ratio_provenance`; `fuel_type` as the first "Powertrain" fact, which for an EV says the motor's electrical and gear-mesh orders are not analysed and replaces the final drive with "Reduction ratio" and drops top gear and engine RPM; `drive_layout` / `propshaft` as the "Drive layout" fact after it, "not provided; driveline advice assumes a propshaft to the rear axle" when unknown and absent for an EV without one; `final_drive_axle` appended to the final drive, e.g. `3.08 (entered by you), front axle`), `metadata.analysis_settings` tire size, `phase_info.phase_pcts`, `d.guided_phases`, `sensor_locations` | Facts grid; `3.15 (car library, model-family estimate)`, `not provided` for a missing reference; speed source as GPS, OBD, entered by hand, or entered by hand as the fallback (unknown slugs read "unknown") |
| Findings table | `d.order_findings[]` | `T1 - once per wheel turn`, `12.1 Hz @ 85 km/h`, km/h range, phases, presence %, location, level (the diagnosed row carries `d.confidence_level`, Weak when the coast-down contradicts it) |
| Amplitude per location | `d.location_amplitudes[]` | `250 mg (34 dB)`, ratio `1.0x`; "not detected" when absent |
| Spectrum | `d.spectrum` (recurring peaks in mg over the moving samples, floor, order markers at the window speed; E1/E2 from the median measured RPM when RPM was measured) | Stems + dashed floor + order lines |
| Amplitude vs speed | `d.amplitude_vs_speed` | Lines per location; shown only for a ≥ 30 km/h sweep |
| Ruled out / not testable | `d.source_checks[]` | `Engine: not testable: no RPM or gear ratio`; `Engine: ruled out: the vibration kept going while coasting in neutral`; `Driveline: no match with the estimated final drive (car-library estimate); not conclusive`; `Engine: no match with the engine orders estimated for top gear; lower gears were not checked`; `Wheels/tires: not testable: the speed was entered by hand, …`; `Brakes: not testable: the drive did not brake firmly from speed`; `Wheels/tires: ruled out: the vibration at the wheel's rhythm came only while braking: …` |
| Shop request | `d.verdict`, `d.source`, `d.order_code`, `d.driveline_parts` | Tire (road force, match-mount, runout), brakes (disc runout on the hub, thickness variation, hub flange runout and caliper slides), driveline (per part, in `driveline_parts` order: gearbox output shaft, final-drive pinion and differential bearings for a car without a propshaft, front propshaft and front differential pinion for AWD; propshaft runout, working angles, rear differential pinion flange; without parts today's propshaft lines), engine, or other |

## Data quality (page 3 or footer)

| Report element | Source |
|---|---|
| Checks | `run_suitability[]` (`check_key` label, `state`, plain meaning; a warning keeps its measured specifics). Frame integrity warns on dropped frames, queue overflows or incomplete raw-replay coverage, so it never reads "no data lost" next to the replay-coverage warning |
| Warnings | `warnings[].code` → plain text, else the resolved `title` |
| Traceability | `run_id`, `sensor_model`, `firmware_version`, `raw_sample_rate_hz`, VibeSensor version |

## Units

- **Strength:** dB everywhere. In the diagnosis block, amplitude at the
  diagnosed order is in mg, always shown next to its dB above floor (see
  `docs/metrics.md`).
- **Frequency:** Hz, one decimal.
- **Speed:** km/h, integers.
- **Format:** Dutch uses a decimal comma.

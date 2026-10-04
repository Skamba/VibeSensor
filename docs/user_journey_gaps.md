# User-journey gaps and work packages

Living tracker for the gaps between [user_journeys.md](user_journeys.md) (the
target state) and the code.

**How to maintain it:**

- Each work-package PR removes the gaps it fixes from this file, deletes the
  package from §2 when it is complete, and rewrites the matching **Today:**
  notes in [user_journeys.md](user_journeys.md).
- Evidence names files and functions, not line numbers.
- Delete this file (and its links) when the last gap is gone.

WP0 (diagnosis queued fixes: J16, J30, J31, J32, J33, J34) shipped in #4109.
J09 (variant tire options) shipped in #4110. WP1a (references may be missing:
J02, J03, J06, J18, J25, the backend half of J01 and the measured-RPM bands of
J24) shipped in #4115. WP1b (provenance-aware source checks: J27, the
analysis half of J15, the report half of J24, and the provenance data for J35)
shipped in #4117. WP3 (speed source, readiness and dashboard UI: J14, J15,
J17, J19, J20, J21, J24 and most of J13) shipped in #4125. WP4 (report and
History wording: J28, J29, J35) shipped in #4127. WP2 (settings and car wizard
UI: J01, J04, J05, J07, J08) shipped in #4128. The rest of J13 (a paired
OBD-II adapter is the speed source until the user picks one) shipped with the
Pi-verification server fixes.

Owner decisions that bound the fixes (settled):

- Estimated engine RPM keeps assuming top gear for the whole drive. No
  gear-shift analysis; the limitation is stated clearly in the UI and report.
- Final drive and top gear are optional; the tire size is the minimum.
- A missing reference gives "couldn't test", never a silent default.

Severity scale:

- **blocks**: the user cannot complete the journey, or would have to invent
  data.
- **misleads**: the user or mechanic is told something untrue or over-confident.
- **friction**: the journey works but is harder than it needs to be.

Ids from earlier reviews are given in brackets (F1–F4, B2).

---

## 1. Gap list (by severity)

### Blocks

None open.

### Misleads

**J12 — EV and PHEV cars are treated as engine cars.**

Evidence:

- The library has 17 EV and 25 PHEV rows, with EV top gear stored as `1.0`
  "Single-speed fixed gear (EV)".
- `fuel_type` is not carried into the car, the run, the analysis or the UI
  (no reference in `domain/car.py`, `run_metadata_builder.py`, `diagnosis.py`).
- The guided coast-down "shift to neutral"
  (`dashboard.guided.coast_down.*`) is meaningless for an EV: the motor stays
  coupled.
- The report says "engine".

Fix:

- **Backend:** Carry `powertrain` (ice/phev/ev) on the car and the run. For an
  EV, rename the engine source to "motor/reduction". Skip the coast-down
  classification, or treat it as not applicable.
- **UI:** Replace the EV guided coast-down step with "Lift off and let the car
  coast; avoid regen if your car allows".

### Friction

**J10 — Model fragmentation and launch-year-only rows.**

Evidence:

- 21 model families are split into several picker entries by year label
  (e.g. X1 F48 ×6, Q5 FY ×5, X3 F25 ×4).
- Generations with launch-year rows only: F10 2011, F20 2011–2012, G11 2016,
  F15 2014–2015.

Fix:

- **Picker:** Group by generation code with a year range ("5 Series F10,
  2010–2017") and resolve the year inside the variant step.
- **Data:** Extend the year ranges where the drivetrain did not change (WP5).

**J23 — No printed SSID/URL card.**

The captive-portal probe responses and the first-load "no internet" hint
shipped in #4112. What remains: ship a QR or label card with the SSID and
`http://10.4.0.1`.

**J11 — Coverage breadth and weak data (data gap).**

Evidence ([user_journeys.md](user_journeys.md) §4):

- Audi and BMW only.
- No Touring bodies, and no Avant except RS 4/RS 6.
- No generation before about 2011.
- 46% of rows have a weak final drive and 43% a weak top gear.

Fix: see WP5.

---

## 2. Work packages (one PR each)

Dependency order:

- WP5, WP6 and WP7 are independent.

### WP5 — Car-library data

- **Covers:** J10, J11.
- **Changes:**
  - Group the picker by generation.
  - Extend year ranges where the drivetrain did not change.
  - Add Touring and Avant bodies for the 3/5 Series and A4/A6.
  - Upgrade the weak final drives by transmission code from official
    catalogues.
  - Never invent values. Leave a field null with an `unresolved` note when it
    is unverifiable, as was done for the 8S TT rows.
- **Validation:** the car-library schema tests and
  `tools/car_library/car_library_stats.py` before and after; update the table
  in [user_journeys.md](user_journeys.md) §4.
- **Depends on:** nothing. Gearboxes with a null final drive are served.

### WP6 — Hotspot and flashing

- **Covers:** J23. J22 (the flasher writes the current SSID/PSK into the
  sensor's NVS) shipped in this PR.
- **Changes:** QR card artwork in `hardware/`.
- **Validation:** a manual phone test.

### WP7 — EV and PHEV handling

- **Covers:** J12.
- **Changes:**
  - Use the plumbed powertrain to rename "engine" to "motor" for EVs.
  - Replace or skip the EV coast-down step and treat the classification as not
    applicable.
  - PHEV caveat: the engine may be off during the run.
- **Depends on:** nothing (WP2 and WP4 shipped). `fuel_type` is already
  carried on the car, the run snapshot and `conditions`; the report and
  History wording it changes lives in `_coverage` / `_conditions` (`report/view_model.py`) and
  `checksModel` (`apps/ui/src/pages/history/history_model.ts`).

---

## 3. Suggested order

1. WP5 and WP6 at any time.
2. WP7 last.

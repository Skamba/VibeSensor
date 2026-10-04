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
shipped in #4117.

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

**J01 [F2] — The manual wizard forces final drive and top gear.**

Evidence (`apps/ui/src/pages/cars/`):

- `wizard_model.ts`: `manualSpecs` returns null unless final drive and top
  gear are set; `firstMissingManualField` lists both fields; `canFinish` for
  manual needs `manualSpecs`.
- `CarWizard.tsx` renders the fields as required, with placeholders
  (`MANUAL_INPUT_EXAMPLES`) that equal the old server defaults.

P1 users cannot find these values and are pushed to copy the placeholder.

Fix:

- **UI:** Mark both fields "(optional)". Add help text:
  - "Final drive (optional) — lets VibeSensor check the propshaft and
    driveline. Find it with a VIN decoder or ask a dealer. Leave empty if
    unknown."
  - "Top gear ratio (optional) — lets VibeSensor estimate engine RPM from
    speed when no OBD-II adapter is connected. Leave empty if unknown."

  Change the placeholders to "e.g. 3.15" / "e.g. 0.67" in grey, or "unknown".
  Show a live "This car can test:" summary next to the form (see J20).
- **Behaviour:** `manualSpecs` returns tire plus nullable ratios. `canFinish`
  needs only a valid tire size. The car routes already accept a null ratio
  (unknown; on an update it clears the stored value).

**J04 — No way to edit a saved car, and the Analysis tab is a dead end.**

Evidence:

- `apps/ui/src/api/settings.ts` has only add, delete and set-active.
- `PUT /api/settings/cars/{car_id}` exists
  (`apps/server/vibesensor/web/settings/cars.py`) but the UI does not call it.
- `completeCar` (`apps/ui/src/pages/cars/cars_store.ts`) switches to the
  Analysis tab, and `apps/ui/src/pages/analysis/analysis_model.ts` exposes
  only the 4 uncertainty percentages.
- Strings that promise editing in Analysis: `settings.car.incomplete_detail`,
  `settings.car.created_detail`, `settings.car.confidence.review_detail`.

A user with winter tires, or who later learns their final drive, must delete
the car and add it again.

Fix:

- **UI:** Add *Edit* on each car row. It opens the Specs step prefilled with
  the tire, final drive, top gear and their provenance chips. Saving calls the
  PUT. Re-word `incomplete_detail` to "Add the missing specs to test the
  driveline/engine — Edit car" and `review_detail` to "Some values are library
  estimates. Edit the car if you know the exact figures." Remove the Analysis
  redirect.
- **Backend:** The PUT accepts partial aspects and per-field provenance. When
  the user edits a value, that field's provenance becomes `user_confirmed`.

**J19 — Start Recording requires a steady ≥ 20 km/h for 8 s.**

Evidence:

- `startDisabled` in `apps/ui/src/pages/dashboard/dashboard_model.ts` follows
  readiness.
- `domain/capture_readiness.py` (20 km/h, 8 s dwell) and `_speed_check` in
  the evaluator.
- The backend does not gate the start (`web/recording.py`).

The driver has to tap the phone while driving at speed, or bring a passenger.
Low-speed complaints (brake judder, pull-away shudder) cannot be captured from
the start.

Fix:

- **Behaviour:** Start is enabled when sensors, car and live speed are present.
  `speed_stable` becomes advice ("Drive steadily above 20 km/h for the hold
  step"). Recording while parked is allowed. The run analysis already ignores
  standstill.
- **UI:** Add "You can start now and drive off — the recording keeps going
  until you stop it or 30 minutes pass."

### Misleads

**J07 — Confidence is not shown in the picker, and the review text appears on
89% of library cars.**

Evidence:

- `gearboxDetail` (`wizard_model.ts`) is "FD: x · Top Gear: y" with no
  confidence.
- The confidence phrase appears only after selection
  (`buildGearboxConfidenceHint` in `tires.ts`).
- `derive_order_analysis_policy`
  (`domain/vehicle_configuration.py`) always sets
  `requires_manual_confirmation=True`. The result is true on 414/467 rows, so
  the warning is noise.

Fix:

- **UI:** Each gearbox option shows a chip: "exact" (official_*), "checked"
  (reputable_secondary_crosschecked), or "estimate" (family_default or
  unverified).
- Replace the review sentence with a consequence: "Final drive is an estimate
  for this model family — driveline results will be marked as estimated. Edit
  the car if you know the exact value."
- **Backend:** Derive `requires_manual_confirmation` only from weak final-drive
  or top-gear confidence. Do not set it for the 276 rows whose fields are all
  official or cross-checked.

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

**J14 — The speed-source page does not explain consequences.**

Evidence: the captions `settings.speed.gps_caption`,
`settings.speed.obd_caption` and `settings.speed.manual_caption`.

Fix: add a three-row table on the page. Its text is in
[user_journeys.md](user_journeys.md) §3.4 (GPS: needs a USB receiver, RPM
estimated in top gear; OBD-II: Bluetooth ELM327, measures RPM; Manual:
fixed-speed test only).

**J15 — A manual speed over-claims before the run.**

Analysis is fixed: with a manual speed every source check that is not a
candidate is `not_testable(manual_speed)`, `manual_speed` is the first weak
reason, and the report says so (`NOT_TESTABLE_MANUAL_SPEED`,
`WEAK_MANUAL_SPEED`).

Evidence (what remains):

- `speed_stable` passes immediately at a set speed ≥ 20 km/h (`_speed_check`
  in the readiness evaluator).
- `reference_ready` passes when the speed is > 0 (`_reference_check`).
- Readiness `capabilities` report wheel, driveline and engine as testable with
  a manual speed.

Fix:

- **UI:** "Speed was entered by hand (fixed {v} km/h); order matching only
  holds if you drove at exactly that speed." The capability line (J20) shows
  nothing as testable with a manual speed.

**J20 — Readiness does not state what the run can test.**

Evidence: the readiness copy is limited to
`dashboard.capture_readiness.reference_ready.ready` ("Live speed and
rotational reference data are ready") and the reason keys in
`apps/ui/src/pages/dashboard/readiness.ts`.

Fix:

- **UI:** Add a capability line under readiness. It is driven by the
  readiness `capabilities` field (`wheel`, `driveline`, `engine`; see
  [run_lifecycle.md](run_lifecycle.md)) and links each item to its fix ("add final drive",
  "connect OBD-II"):
  "This run can test: Wheels/tires ✓ · Driveline ~ estimated final drive ·
  Engine ~ RPM estimated (top gear only)".

**J24 [F4] — The top-gear assumption is never stated.**

Evidence:

- The guided-drive strings `dashboard.guided.*` have no gear guidance.
- The band labels `bands.*` are "Engine 1x".

The report half is fixed: `conditions.rpm_source` is `estimated_top_gear`,
the engine check is `ruled_out_estimated(top_gear_assumed)`, and the report
prints `RPM_ESTIMATED_TOP_GEAR` and `RULED_OUT_ENGINE_TOP_GEAR` ("no match
with the engine orders estimated for top gear; lower gears were not
checked").

Fix:

- **UI:** The sweep step reads "Drive in top gear (or D) — without OBD-II, the
  engine check assumes top gear." The band legend reads "Engine 1× (est., top
  gear)", or "(measured)" with OBD.
- The live bands already use fresh OBD-II RPM, and a missing reference blanks
  only its own family; the legend should grey out the missing families with
  "needs final drive" / "needs top gear or OBD-II".

**J28 — History does not show what was tested, and the no-fault text
over-claims.**

Evidence:

- `apps/ui/src/pages/history/` reads neither `source_checks` nor
  `conditions`.
- `history.verdict.no_fault_body` "Nothing stood out above normal road and
  engine vibration in the speeds you drove." shows even when the engine or
  driveline was not testable.

Fix:

- **UI:** Add a "Checked / Couldn't check" block using the PDF strings.
- The no-fault text reads "Nothing stood out in the checks we could run
  ({list}). Not checked: {list} — {fix}."

**J29 — Page 1 "Not covered" omits a missing final drive or tire.**

Evidence: `_coverage` (`report/view_model.py`) adds only `NOT_COVERED_RPM`.

Fix: build the list from `source_checks` entries with status `not_testable`
(and the estimated variants), using the `NOT_TESTABLE_*` keys in
`report_i18n.json`.

**J35 — Report ratios have no provenance.**

Evidence: `_conditions` (`report/view_model.py`) and `COND_RATIOS_VALUE`
(`report_i18n.json`) print bare numbers.

Fix: print "Final drive 3.15 (library: family default) · Top gear 0.67
(library: official) · Tire 225/45 R18 (you)". A missing value prints "— not
provided". The provenance is in `diagnosis.conditions`
(`tire_provenance`, `final_drive_provenance`, `gear_ratio_provenance`).

### Friction

**J05 — Typing a custom brand shows a false "library unavailable" error.**

Evidence:

- `submitCustom` → `selectBrand` → types fetch (`wizard_store.ts`).
- The server returns 404 for an unknown brand (`web/car_library.py`).
- The wizard then shows `settings.wizard.load_failed_types` /
  `load_failed_hint` ("The car library is unavailable right now…").

Fix:

- **UI:** For a brand that is not in the brand list, skip the fetch and go
  straight to free-text type and model. Show the info line "No library data
  for {brand} — you'll enter the tire size yourself; ratios are optional."
- **Backend (optional):** return `200 []` for an unknown brand.

**J08 — No field help and no "I don't know".**

Evidence: `CarWizard.tsx` has field labels only. The tire size cannot be
pasted as "225/45 R18".

Fix:

- Add an info line per field with where to find it (tire: sidewall or the door
  jamb placard; final drive: VIN decoder, dealer, or the differential tag).
- Add a single "225/45 R18" text input that fills the three tire fields.
- Add an "I don't know" link that clears the field (needs J01).

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

**J13 — The default source is GPS, but there is no GPS receiver in the BOM and
the Pi has one USB port.**

Evidence:

- `SpeedSourceConfig.default` (`speed/speed_source_config.py`) is GPS.
- The `hardware/README.md` BOM has none.
- The Pi 3 A+ has a single USB 2.0 port, which the USB internet uplink
  (`settings.internet.hint`) also needs.

Fix:

- **Docs and BOM:** List a recommended u-blox USB receiver, or recommend OBD-II
  as the primary source.
- **UI:** When GPS is selected and gpsd reports no device: "No GPS receiver
  found — plug in a USB GPS receiver or switch to OBD-II."
- Consider defaulting to OBD-II when a paired adapter exists.

**J17 — OBD-II is Bluetooth only, and the page does not say so clearly.**

Evidence: `settings.speed.obd_caption` mentions Bluetooth but not that Wi-Fi
dongles cannot work; wlan0 is the AP, so Wi-Fi ELM327 dongles cannot connect.

Fix: add a caption, "Bluetooth ELM327 adapters only — Wi-Fi OBD dongles are
not supported", and put a link to it in the BOM.

**J21 — No sensor layout or mounting guidance.**

Evidence: there are no strings for it in the UI catalogs. Readiness only warns
below 3 sensors (`domain/capture_readiness.py`,
`dashboard.capture_readiness.sensors_ready.limited_sensor_coverage`).

Fix: add a "Where to mount" panel in Sensors. It shows the recommended layouts
with what each can localise ([user_journeys.md](user_journeys.md) §5.2) and the
mounting rules. The readiness line repeats the layout consequence.

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

- WP2, WP3 and WP4 have no dependencies.
- WP5 and WP6 are independent.
- WP7 depends on WP2 and WP4.

### WP2 — Settings and car wizard UI

- **Covers:** J01, J04, J05, J07, J08.
- **Changes:**
  - Optional ratio fields with help text and the "This car can test" sidebar.
  - Car *Edit*, using the existing PUT.
  - Re-word the `incomplete_detail` and `review_detail` strings.
  - Custom brand without a fetch.
  - Confidence chips on gearbox options.
  - A tire-size paste field.
  - EN and NL catalogs updated together.
- **Backend tweak in the same PR:** `requires_manual_confirmation` derived
  only from weak fields (`derive_order_analysis_policy` in
  `domain/vehicle_configuration.py`).

### WP3 — Speed source, readiness and dashboard UI

- **Covers:** J13, J14, J15 (readiness and UI), J17, J19, J20, J21, and the
  live and guided half of J24 (UI side).
- **Changes:**
  - Speed-source consequence table and a "no GPS receiver" hint.
  - Bluetooth-only caption.
  - Start enabled without the speed dwell.
  - Capability line.
  - Sensor layout and mounting panel.
  - Guided step wording "top gear (or D)".
  - Band legend "est., top gear" / "measured".
- **Validation:** UI tests plus the e2e suite (start gating).
- **Note:** the capability line should use the same statuses as the source
  checks (`ruled_out_estimated`, `not_testable(manual_speed)`); readiness
  `capabilities` do not yet reflect weak library ratios or a manual speed.

### WP4 — Report and History wording

- **Covers:** J28, J29, J35.
- **Changes:**
  - "Not covered" built from `source_checks`.
  - Ratios printed with provenance.
  - History "Checked / Couldn't check" block.
  - Honest no-fault text.
  - EN and NL in both `report_i18n.json` and the UI catalogs.

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
- **Depends on:** WP2 (car profile), WP4 (wording). `fuel_type` is already
  carried on the car, the run snapshot and `conditions`.

---

## 3. Suggested order

1. WP2.
2. WP3 and WP4.
3. WP5 and WP6 at any time.
4. WP7 last.

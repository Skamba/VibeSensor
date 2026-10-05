# User journeys and expectation setting

This document describes who uses VibeSensor, what each of them knows, and the
end-to-end journeys the software must support, from unboxing to a re-test after
a repair. It is written as the **target state**. Where today's code does
something different, a short **Today:** note says so and names a gap id
(`J01`…) from [user_journey_gaps.md](user_journey_gaps.md), which also names
the work package that fixes it. When a work package lands, its PR removes the
gap from the tracker and rewrites the matching **Today:** note.

Use it when you change the car wizard, the speed-source or readiness logic, the
diagnosis source checks, or the report wording. The rule of thumb: **the
software asks only for what it needs, tells the user what each missing piece
costs, never fills a gap with a silent default, and never claims more than the
recording tested.**

---

## 1. Personas

Three personas cover the product. They are based on what owners can actually
find on or about their car and on what workshops ask for when they receive a
vibration complaint.

### P1 — Owner with a vibration and no technical data (primary)

- Knows make, model and roughly the year. Can read the tire size off the
  sidewall or the placard in the driver's door jamb, which tire makers call
  the most reliable source because it shows the size the car was built
  around ([Continental](https://continentaltire.com/learn/how-read-your-tire-sidewall),
  [TireGrades](https://tiregrades.com/learn/where-to-find-tire-size/)).
- Does **not** know the final-drive ratio or gear ratios. On European cars there
  is no axle code on the door sticker, unlike US trucks
  ([GarageGuide](https://garageguide.blog/how-to-figure-out-axle-ratio)). Finding
  it takes a VIN decoder and a parts catalogue (for BMW, RealOEM/ETK), or
  reading a code stamped on the differential
  ([E46 Fanatics](https://www.e46fanatics.com/threads/final-drive-ratio.1320710/),
  [SRS concept](https://srs-concept.com/bmw-differentials-gear-set-easy-identification/)).
- Has a phone and the VibeSensor kit. The kit's bill of materials
  (`hardware/README.md`) has no GPS receiver and no OBD adapter.
- Describes the problem the way a workshop asks about it: where it is felt
  (steering wheel, seat), at what speed, and whether it changes when
  accelerating or coasting
  ([Tire Review](https://www.tirereview.com/diagnosing-vibration-issues/),
  [Nissan worksheet](http://www.nissantechnicianinfo.mobi/htmlversions/Spring_2012/Vibration.html)).
- **Needs:** an answer they can act on (wheel/tire, driveline or engine, and
  where), plus a clear statement of what was *not* checked. They should not be
  asked for numbers they cannot find.

### P2 — Enthusiast who knows some specs or owns an OBD-II dongle

- Knows the tire size, often the gearbox, and sometimes the final drive from a
  forum or a VIN decoder.
- May own a cheap ELM327 dongle. Every EU petrol car first registered from
  2001 and every diesel from 2004 has an EOBD port within reach of the driver
  ([Wikipedia: OBD](https://en.wikipedia.org/wiki/On-board_diagnostics),
  [OBDLink](https://obdlink.nl/en/what-is-eobd)), and ELM327 Bluetooth adapters
  are the common consumer tool ([Car Scanner](https://www.carscanner.info/choosing-obdii-adapter/)).
  Many of these dongles are Wi-Fi rather than Bluetooth. VibeSensor only
  supports Bluetooth, because the Pi's Wi-Fi runs the hotspot.
- **Needs:** to know what the extra data buys. Measured RPM makes the engine
  check independent of gear and final drive. An exact final drive makes a
  driveline "ruled out" trustworthy. Partial knowledge must still be useful.

### P3 — Mechanic or tire shop receiving the report

- Works from symptoms: speed range, where it is felt, and the order and
  frequency of the vibration. Workshops use an electronic vibration analyser
  (for example GM's EVA) to get first/second-order wheel, driveshaft and engine
  frequencies ([MOTOR](https://www.motor.com/magazine-summary/fixing-vexing-vibrations-march-2018/),
  [Saab WIS: EVA](https://saabwisonline.com/9-4x/2011/1-service/saab-service-ww/technical-description/electronic-vibration-analyzer-eva-description-and-operation),
  [Tire Review: driveshaft orders](https://www.tirereview.com/driveshaft-vibration-order-identifying-and-calculating-vibration-frequencies/)).
- **Needs:** the test conditions with their provenance. That means whether RPM
  was measured or estimated (and the top-gear assumption), whether the ratios
  came from the owner, the library, or nowhere, the speed source, and the
  sensor positions. It also needs what was ruled out versus what was not
  testable. This is what page 2 of the PDF is for
  ([report_pipeline.md](report_pipeline.md)).

---

## 2. Expectation-setting principles

These are the rules the software follows. Each gap in
[user_journey_gaps.md](user_journey_gaps.md) breaks at least one of them.

1. **Ask for the minimum; explain each field.** The minimum is the car
   identity (any brand, free text allowed) and the tire size. Final drive and
   top gear are optional. Every field says what it enables ("Final drive: needed
   to check the propshaft/driveline; leave empty if unknown") and where to find
   it.
2. **Prefill whatever the library knows, with its provenance.** A library value
   carries its confidence (`official_exact` … `unverified`) from the picker to
   the saved car, the run metadata, the diagnosis and the report.
3. **Never substitute a silent default.** A missing reference stays missing.
   The source it would have tested becomes "couldn't test: <what's missing> —
   <how to add it>". Nothing in the analysis path reads a tire size, final
   drive or gear ratio unless a user or the library supplied it.
4. **Claim only what was tested.**
   - "Ruled out" needs trustworthy references *and* adequate speed coverage.
   - A family-default or unverified ratio, a manual fixed speed, or an
     estimated RPM gives a hedged ruled-out ("no match with the estimated final
     drive").
   - With no reference at all, the source is "not tested".
5. **State the limitation where it bites.** Estimated engine RPM assumes top
   gear for the whole drive. This is a kept limitation (owner decision); there
   is no gear-shift analysis. The guided-drive step, the live band label, the
   readiness line, the report conditions and the engine ruled-out sentence all
   say so.
6. **Readiness separates blockers from reduced capability.**
   - Blockers are things without which a recording is worthless: no sensors, no
     car, no live speed.
   - Reduced capability is reported in a "this run can test…" line and never
     blocks.
7. **One vocabulary in the UI and the PDF.** The same verdict, confidence
   (Strong/Moderate/Weak), ruled-out and couldn't-test wording appears in
   History and in the report.

---

## 3. Journeys

Each step lists four things:

- **Know/do:** what the user must know or do.
- **Prefill:** what the software fills in for them.
- **Tell:** what it tells them about the consequences.
- **Branches:** the failure and partial-information branches.

UI strings are named by their key in `apps/ui/src/i18n/catalogs/en.json`;
report strings by their key in `apps/server/vibesensor/data/report_i18n.json`.

### 3.1 First boot and connecting to the Pi hotspot

- **Know/do:** Power the Pi in the car. Join the Wi-Fi network `VibeSensor`,
  which is open by default (`ap.ssid` / `ap.psk` in
  `apps/server/vibesensor/app/config_defaults.py`,
  [configuration_reference.md](configuration_reference.md)). Open
  `http://10.4.0.1` (`infra/pi-image/pi-gen/README.md`).
- **Prefill:** The hotspot watchdog brings the AP back if it drops
  (`infra/pi-image/pi-gen/README.md`).
- **Tell (target):**
  - A printed card or label carries the SSID and the URL, ideally as a QR code.
  - The Pi answers captive-portal probes so the phone opens the UI by itself.
  - The UI explains that the phone may say "no internet". On some Android
    versions the phone otherwise keeps routing through mobile data or moves
    away from the network
    ([TechWiser](https://techwiser.com/fix-android-connected-to-wi-fi-but-no-internet/),
    [SafeSky](https://docs.safesky.app/books/safesky-pilot-playbook/page/using-mobile-internetdata-while-connected-to-a-wifi-network-iosandroid)).
  - **Today:** the captive portal and the hint exist. The printable card is
    `hardware/qr_card_example.pdf` for the stock network;
    `tools/hardware/make_qr_card.py` makes one for a custom `ap.ssid` /
    `ap.psk` ([hardware/README.md](../hardware/README.md)).
- **Branches:**
  - Port 80 is unavailable: use port 8000 (pi-gen README).
  - The operator sets `ap.psk` as the docs advise: sensors must be re-flashed
    from *Settings → ESP Flash*, which writes the Pi's current `ap.ssid` /
    `ap.psk` into the sensor's NVS
    (`apps/server/vibesensor/updates/firmware/sensor_wifi_nvs.py`). Sensors
    flashed elsewhere only know the open `VibeSensor` network.

### 3.2 Flashing and adding sensors, assigning mounting locations

- **Know/do:**
  - Sensors (ATOM Lite + ADXL345) ship flashed. Re-flash over USB from
    *Settings → ESP Flash* (`apps/ui/src/pages/esp_flash/EspFlash.tsx`).
  - Power the sensors and mount them.
  - In *Settings → Sensors* (`apps/ui/src/pages/sensors/Sensors.tsx`), pick a
    location per sensor. Use *Identify* to blink the LED and find which
    physical sensor is which (`firmware/esp/README.md`).
- **Prefill:**
  - A sensor's name defaults to its MAC (`settings.sensors.hint`).
  - A location is inferred from names such as "front left" or "driver"
    (`locationCodeForClient` in `apps/ui/src/sensor_locations.ts`).
- **Tell (target):**
  - Recommended layouts and what each can do:
    - four wheel-area sensors plus one cabin sensor gives corner localisation;
    - wheels only;
    - cabin only cannot name a wheel;
    - one sensor gives the source type only.
  - Mounting rules: a rigid part near each wheel such as the knuckle or strut
    base (never the rotating wheel), with a firm fixing.
  - The readiness line repeats this. **Today:** the Sensors tab has a "Where to
    mount the sensors" panel (`MountingGuide` in
    `apps/ui/src/pages/sensors/Sensors.tsx`) with the layouts, the mounting
    rules and the current layout's consequence (`apps/ui/src/sensor_layout.ts`);
    the Live capability line repeats the consequence.
- **Branches:**
  - A sensor runs older firmware than the Pi's bundle: each Sensors row shows
    the firmware version the sensor reports and its `firmware_status` (up to
    date / outdated / status unknown, from
    `apps/server/vibesensor/domain/sensor_firmware.py`). While any sensor is
    outdated, a notice says the update needs a USB cable into the Pi and its
    *Update sensor firmware* button opens *Settings → ESP Flash*. Sensors
    cannot be updated over Wi-Fi.
  - A sensor has no location: readiness fails `sensor_locations_missing`
    (`_sensors_check` in
    `apps/server/vibesensor/recording/capture_readiness_evaluator.py`).
  - Frame loss: readiness waits out a 10 s quiet period (same function).
  - A late sensor: chunks sent before its clock syncs are dropped, and the
    sensor is aligned from its first synced chunk
    ([run_lifecycle.md](run_lifecycle.md), "Recording active").

### 3.3 Adding a car

Entry point: *Settings → Car → + Add Car*. This opens the five-step wizard
(Brand → Type → Model → Variant → Specs) in
`apps/ui/src/pages/cars/CarWizard.tsx`, with its rules in `wizard_model.ts` and
its state in `wizard_store.ts`. The header shows the step and the picks so far
on one line, e.g. "BMW · SUV · X1 (F48, 2015–2022)" (`selectionTrail`); only
the step content scrolls, and each step starts at its top. On a phone the
"This car can test" and "Your car" card shows only on the specs step, below
the form.

#### 3.3a Library path (Audi or BMW, the brands included today)

- **Know/do:** Pick brand, body type, model (one entry per generation, with
  its code and model years, e.g. "X1 (F48, 2015–2022)"), variant
  (engine/drivetrain, with its model years), then a tire option and a
  gearbox. Where an engine's gearbox data changed over the years, the
  variant is listed once per model-year period ("xDrive25d (2021–2022)"), so the
  variant step resolves the year (`_variants_for_generation` in
  `apps/server/vibesensor/settings/car_library.py`, `variantDetail` in
  `wizard_model.ts`, which leaves the years out of the detail line when the
  name already carries them).
- **Prefill:**
  - The model list shows the default tire size (`CarWizard.tsx`).
  - The tire options come from the variant (`resolveTireOptions` in
    `wizard_model.ts`): the union of its rows' options, one per size
    (`_union_tire_options` in `apps/server/vibesensor/settings/car_library.py`).
  - Each gearbox row carries final drive, top gear and per-field confidence
    (`_gearbox_row_from_configuration` in `car_library.py`). A ratio the
    library row leaves unresolved is served as `null` without a confidence;
    the wizard leaves that field empty ("unknown"), never a default.
  - The first tire option, and the gearbox when there is only one, are
    preselected (`loadSpecs` in `wizard_store.ts`). Choosing a tire or a
    gearbox fills the specs form, so the user can change any value, for
    example for winter tires (`tireInputsFromOption` /
    `ratioInputsFromGearbox` in `wizard_model.ts`). The highlighted tire
    option follows the tire fields: a size edited to another option's size
    highlights that option and takes its source; a size no option has
    highlights none and is the user's (`tireOptionForInputs`).
- **Tell:**
  - Each gearbox option shows its final drive and top gear with a confidence
    chip: "exact" (official), "checked" (cross-checked secondary source),
    "estimate" (family default or unverified) or "unknown" (`gearboxParts` in
    `wizard_model.ts`, `ProvenanceChip` in `CapabilityList.tsx`). The specs
    form shows the same chip on each value; a typed value is "yours"
    (`specProvenance`).
  - When a kept value is an estimate, the action hint says what that does to
    the result, e.g. "Final drive is an estimate for this model family:
    driveline results will be marked as estimated" (`estimateNoteKey`,
    `settings.car.estimate.*`).
  - The side card (below the form on a phone) shows "This car can test" for
    the values on the form
    (`carCapabilities` in `apps/ui/src/capabilities.ts`, the same vocabulary
    as the Live capability line).
  - `requires_manual_confirmation` is set only when the final drive or top
    gear is weak (79 of 580 rows, see §4). A saved car's flag follows the
    same rule (`CarOrderReferenceStatus.requires_manual_confirmation`); it is
    derived on every load, so cars saved under the older rule (which also
    counted tire size and the gearbox name) no longer keep a stale `true`.
- **Branches:**
  - The library has no final drive for the gearbox (13 rows). The gearbox is
    still offered with `final_drive_ratio: null`
    (`_gearbox_row_from_configuration`) and its final drive chip reads
    "unknown"; the car saves without a final drive and the driveline is
    "couldn't test" until the user adds the value.
  - Library load fails: an error with Retry and "Continue with manual specs"
    (`CarWizard.tsx`).

#### 3.3b Manual path (any other brand, or a model the library lacks)

- **Know/do:** Type a brand, type and model, then enter the tire width, aspect
  and rim. Final drive and top gear are entered **if known**.
- **Prefill:**
  - A brand or type that is not in the library skips the library lists (no
    fetch) and says "No library data for {brand}: you'll enter the tire size
    yourself; final drive and top gear are optional" (`submitCustom` /
    `loadCurrentStep` in `wizard_store.ts`). A typed name that matches a
    library entry, in any case, uses the library.
  - Each field says what it enables and where to find it (tire: sidewall or
    door-jamb sticker; final drive: VIN decoder, differential tag or dealer;
    top gear: estimated RPM, which assumes top gear or D)
    (`settings.car.*_help`).
  - The tire size can be pasted as on the sidewall, e.g. "225/45 R18" or
    "P225/45ZR18 94W", and fills the three tire fields (`parseTireSize`);
    clearing it clears them. It stays in sync the other way too: once a tire
    pick, a library or saved-car prefill, or an edit of the three fields
    changes them, it shows their size, e.g. "225/55 R17"
    (`tireSizeText` in `wizard_store.ts`, `tireSizeFromInputs`).
  - Final drive and top gear are marked "(optional)", with a neutral
    "unknown" placeholder; "I don't know" clears the field.
- **Validation:** only the tire size is required; a ratio must be empty or
  a positive number (`firstInvalidField` / `canFinish`). Typed values are
  saved as `user_confirmed`, empty ratios as `null` with no confidence
  (`carRequest` in `wizard_model.ts`).
- **Tell:** the "This car can test" card updates as the user types:
  - tire only → wheel/tire;
  - plus final drive → driveline;
  - plus top gear → engine (RPM estimated from speed, assuming top gear);
  - a hint that an OBD-II adapter measures RPM without the ratios.
- **Branches:**
  - The user enters only the tire size: the car saves, and the driveline and
    engine show "couldn't test".

#### 3.3c Editing later

- Each car row shows its tire, final drive and top gear with a confidence
  chip, a compact "This car can test" list, and *Edit* (*Finish setup* on a
  car without a tire size) (`carRows` in
  `apps/ui/src/pages/cars/car_list_model.ts`).
- *Edit* reopens the specs step prefilled with the saved values and their
  provenance (`openEditor` in `wizard_store.ts`, `editTarget` in
  `wizard_model.ts`). Saving sends only the changed values to
  `PUT /api/settings/cars/{id}` (`editRequest`, `saveCarEdits` in
  `cars_store.ts`); a cleared ratio is sent as `null` and unset. The server
  marks each edited value `user_confirmed` and keeps the others' provenance
  (`update_car` in `apps/server/vibesensor/settings/car_settings.py`).
- A car saved with different front and rear tires says so in the editor;
  changing the size there sets one size on all four wheels.
- Runs recorded under the old values keep them and History shows "car
  settings changed" (`add_current_context_warnings` in
  `apps/server/vibesensor/recording/run_context.py`).
- **EVs and PHEVs:** a library row carries its powertrain (`fuel_type`:
  ICE, PHEV or EV). Where the library does not say (a car entered by hand, or
  a saved car without one), the specs step asks "Powertrain" (*Petrol or
  diesel*, *Plug-in hybrid*, *Electric*, or *Not sure*, which is analysed as a
  combustion-engine car) and the editor sends it with `PUT` (`asksPowertrain`,
  `wizardFuelType` in `wizard_model.ts`). For an EV the specs step hides the
  top gear, labels the final drive "Reduction ratio", and names the driveline
  family "Electric motor" and the engine "not applicable" in "This car can
  test" (`carCapabilities`, `capabilityFamilyKey` in
  `apps/ui/src/capabilities.ts`). A library EV row has no top gear (the
  reduction ratio is its final drive), and a saved EV car keeps none
  (`Car` in `apps/server/vibesensor/domain/car.py`), so an EV asks for
  confirmation only when its reduction ratio is an estimate. See §5.3 for
  what the powertrain changes in the analysis.

### 3.4 Choosing a speed source

Entry point: *Settings → Speed Source*
(`apps/ui/src/pages/speed_source/SpeedSource.tsx`). Until the user picks a
source, it is OBD-II when an adapter is paired and GPS otherwise
(`SpeedSourceConfig` in `apps/server/vibesensor/speed/speed_source_config.py`):
pairing an adapter makes it the source, and unpairing goes back to GPS. A
source the user saved is never changed (`speedSourceChosen`). Settings saved
before the choice was recorded count GPS as not chosen.

| Source | Hardware | What it enables | What it cannot do |
|---|---|---|---|
| GPS | A USB GPS receiver read through gpsd ([configuration_reference.md](configuration_reference.md)). It is listed as an alternative in the [hardware BOM](../hardware/README.md), and the Pi 3 A+ has a single USB port ([Pishop](https://www.pishop.us/product/raspberry-pi-3-model-a-plus-512mb-ram/)) that USB internet also uses. | Live speed for wheel and driveline orders; sweeps; coast-down. | RPM is estimated from ratios, assuming top gear. |
| OBD-II | A **Bluetooth** ELM327 adapter paired with the Pi (`settings.speed.obd_caption`). Wi-Fi dongles cannot be used. | Live speed *and measured RPM*. With measured RPM the engine is testable without tire size or final drive (`_source_checks` in `apps/server/vibesensor/analysis/diagnosis.py`). | Nothing extra: readiness needs fresh RPM, not the ratios. |
| Manual | None. | Only a test held at that one fixed speed (`apps/server/vibesensor/speed/speed_resolution.py`). | Sweeps, amplitude vs speed, and the coast-down check. Every sample is treated as being at the set speed. |

- **Tell (target):** each choice explains what it enables, using the table
  above. Choosing manual shows "Only for a steady-speed test at exactly this
  speed. Results will be hedged." **Today** the captions say this, and a "What
  each source can do" table (`settings.speed.compare.*`) repeats the table
  above.
- **Branches:**
  - GPS selected with no receiver or no fix: readiness waits for a live reading
    (`_reference_check` in `capture_readiness_evaluator.py`). When gpsd has
    never seen a receiver, the page, the Live setup panel and the spectrum say
    "No GPS receiver found — plug in a USB GPS receiver or switch to OBD-II"
    (`gpsReceiverMissing` in `apps/ui/src/speed_source.ts`).
  - Live data goes stale with a manual fallback set: the fallback is used,
    readiness says so, and the report names the source "entered by hand"
    (`SPEED_SOURCE_FALLBACK_MANUAL`). The Live speed readout, the capability
    note and the Speed source summary name why the fallback is used (the same
    "No GPS receiver found" text, "GPS has no fix yet", or "No live OBD-II
    speed"; `fallbackReasonKey` in `apps/ui/src/speed_source.ts`) instead of
    calling it a manual override.
  - Scanning for or pairing an OBD-II adapter: the Pi 3 A+ shares one radio
    between Wi-Fi and Bluetooth, so a scan or pairing briefly interrupts sensor
    data. The page says so (`settings.speed.obd_scan_interrupts`), scans only
    when asked, and the server refuses both with 409 while recording
    (`create_obd_admin_routes` in `apps/server/vibesensor/web/settings/obd.py`).
    The frames lost meanwhile are marked as expected loss
    (`ClientRegistry.expecting_frame_loss`) and do not raise a sensor
    frame-loss warning.

### 3.5 Pre-drive readiness

Backend: `CaptureReadinessTracker` → `evaluate_capture_readiness` in
`apps/server/vibesensor/recording/capture_readiness_evaluator.py`. It runs
three checks:

- `sensors_ready`
- `reference_ready`
- `speed_stable`

The UI renders it in `apps/ui/src/pages/dashboard/readiness.ts` and
`dashboard_model.ts`.

- **Target:**
  - Block only on: no live sensors, unassigned locations, no active car, and
    no working speed source.
  - Show a capability line, for example "This run can test: wheels/tires ✓ ·
    driveline ~ (final drive is a library estimate) · engine ~ (RPM estimated,
    top gear only)", with a link to fix each item (J20).
  - Show the sensor layout consequence (J21).
  - Allow Start while parked, so the run covers pulling away and low speeds.
    The steady-speed dwell becomes advice for the steady-hold step.
- `reference_ready` needs only an active car and a working live speed (OBD-II
  also fresh RPM); missing references never block. The readiness payload
  carries a non-blocking `capabilities` field (`_capabilities` in
  `apps/server/vibesensor/recording/capture_readiness_evaluator.py`) for the
  capability line.
- **Today:** as the target. `speed_stable` only warns (a "Tip" for the hold
  step), so Start is enabled while parked, with "You can start now and drive
  off". The capability line (`capabilityModel` in
  `apps/ui/src/pages/dashboard/readiness.ts`) shows each family as tested,
  estimated (weak library ratios, top-gear RPM) or not tested, with a fix
  button. With a typed-in speed it shows nothing as tested and says the
  matching only holds at exactly that speed.

### 3.6 Recording: free drive and guided drive

- **Free drive:** Press Start and drive.
  - Recording auto-stops after 30 minutes
    (`apps/server/vibesensor/recording/lifecycle_state.py`), with the notice
    `dashboard.logging.auto_stopped_max_duration`.
  - It also auto-stops with `no_data_timeout` when the sensors go silent
    ([run_lifecycle.md](run_lifecycle.md)).
- **Guided drive (optional):** three steps posted to
  `/api/recording/guided-phase` (`dashboard.guided.*` strings).
  1. Sweep from 50 to 120 km/h (`GUIDED_SWEEP_FROM_KMH` /
     `GUIDED_SWEEP_TO_KMH` in `apps/ui/src/config.ts`).
  2. Hold at the worst speed for about 20 s.
  3. Coast down in neutral by about 30 km/h.

  The coast-down classifies the vibration as following road speed or engine
  speed (`_speed_dependence` in `diagnosis.py`), and a contradicting coast-down
  downgrades the verdict (`_contradicts_coast_test`).
- **Tell (target):**
  - The sweep and hold steps say "in top gear (or D) — engine checks assume top
    gear unless an OBD-II adapter measures RPM" (owner decision).
  - The live band labels read "Engine 1× (est., top gear)", and use measured
    RPM when OBD supplies it.
  - For EVs the coast-down step is skipped: the motor cannot be decoupled,
    and regenerative braking makes a lift-off coast no cleaner.
  - The live bands use fresh measured OBD-II RPM for the engine, and a
    missing reference blanks only its own family (`vehicle_orders_hz` in
    `apps/server/vibesensor/dsp/order_bands.py`).
  - **Today:** the guided steps and the band labels say it ("Engine 1x (est.,
    top gear)" / "(measured)"), and the spectrum's band status names what a
    blank family needs ("needs final drive", "needs top gear or OBD-II"). The
    report states it too (`RPM_ESTIMATED_TOP_GEAR`,
    `RULED_OUT_ENGINE_TOP_GEAR`). For an EV the guided drive is the sweep and
    the hold, without the top-gear sentence (`guidedTestModel` in
    `apps/ui/src/pages/dashboard/dashboard_model.ts`); the live spectrum
    labels the driveline band "Motor 1x" and draws no engine bands
    (`orderBands`, `bandStatus` in `spectrum_model.ts`).
- **Branches:**
  - A reload mid-run restores the guided panel ([run_lifecycle.md](run_lifecycle.md)).
  - Speed below 20 km/h or unstable before Start is only advice for the hold
    step; it does not disable Start.

### 3.7 Post-analysis and viewing results (History)

- After Stop, the run is queued for post-analysis
  ([run_lifecycle.md](run_lifecycle.md) §3). The Live page shows "Run … is
  being analyzed" and then "ready in History" (`dashboard.logging.*`).
- History shows the following (`history.*` strings):
  - the verdict: no significant vibration / not enough evidence / fault;
  - the confidence level with its action meaning (Strong: go fix it;
    Moderate: do the cheap confirming check first; Weak: don't buy parts;
    record again);
  - the zone and the speeds driven;
  - a recapture recipe for weak runs.
- History also shows, for every run, a "Checked / Couldn't check" block built
  from the diagnosis `source_checks` in the PDF's words (`history.checks.*`):
  each source that was matched, ruled out, or checked only against an estimate
  (with the estimate named), and each source that could not be tested with
  what is missing and how to add it. Under it, "Car references" lists the
  tire circumference, final drive, top gear ratio and engine RPM source with
  their provenance, as on PDF page 2 (`history.references.*`).
- A no-fault run says only what it could check and what it could not
  (`history.verdict.no_fault_body`, `history.verdict.no_fault_not_checked`):
  "Nothing stood out in the checks this run could make: wheels/tires. Not
  checked, so not shown to be fine: driveline and engine." It never implies
  the car is fine for a source that was not testable.
- Each failing run-suitability check (speed variation, sensor coverage, frame
  integrity, …) is a warning banner at the top of the run detail, titled with
  the check and worded as its row on the PDF's data-quality page
  (`apps/server/vibesensor/report/run_quality.py`, used by both). A run
  warning that a failing check already states in full (the incomplete raw
  capture) is shown once, on the PDF too.

### 3.8 The PDF for owner and mechanic

`GET /api/history/{run_id}/report.pdf?lang=en|nl`
([report_pipeline.md](report_pipeline.md)).

- **Page 1 (owner):**
  - verdict and confidence;
  - a plain sentence;
  - a car diagram with a corner or zone;
  - the next step and a fallback step;
  - how to check the fix (re-run the test);
  - for a no-fault run, "What this test covered / Not covered".
- **Page 2 (mechanic):**
  - test conditions: tire and circumference, ratios, speed source, RPM
    measured or estimated, phases, guided steps, sensors;
  - the worksheet and per-location mg;
  - ruled-out and not-testable sources;
  - the spectrum with T/P/E markers (E markers from measured RPM when OBD-II
    supplied it);
  - amplitude vs speed;
  - the shop request.
- **Tell:**
  - Every reference shows its provenance (`_conditions` in
    `apps/server/vibesensor/report/view_model.py`, `PROVENANCE_*`): "Final
    drive 3.15 (car library, model-family estimate)", "Top gear ratio not
    provided", "Tire size 225/45R18, circumference 1.984 m (entered by you)",
    and "Engine RPM not measured; estimated from speed assuming top gear".
  - Ruled-out lines are hedged when they rest on estimates: a family-default
    or unverified library ratio gives `ruled_out_estimated` ("not
    conclusive"), estimated RPM gives "estimated for top gear; lower gears
    were not checked", and a manual speed gives "not testable".
  - A no-fault page 1 names what was checked, hedged where it rests on an
    estimate, and what was not. Its "Not covered" list comes from
    `source_checks` (`_coverage` in `view_model.py`): each untested or
    estimate-based source with how to close the gap ("Driveline: no
    final-drive ratio — add it to the car in Settings if you know it
    (optional)."), then the speeds and driving the run left out.

### 3.9 Re-test after a fix

- **Know/do:** Repeat the same drive with the same car, the same sensor
  positions and, ideally, the guided steps. Page 1 tells the user what a pass
  looks like.
- **Prefill:** The active car and sensor locations persist.
- **Tell:** No built-in before/after comparison (owner decision). If the car
  settings changed between runs, the older run shows "Vehicle profile settings
  changed after this run" (`report_i18n.json`).
- **Target addition (low priority):** let the user label a run ("before
  balance", "after balance") so the two runs are easy to find in History.

### 3.10 Updates

- *Settings → System Update* updates from GitHub, either over temporary Wi-Fi
  credentials (the hotspot pauses) or over a USB internet uplink
  (`settings.update.hint`, `settings.internet.hint`).
- The updater installs into an A/B venv, smoke-tests it, and reverts
  automatically if the service is unhealthy after a restart.
- **Branch:** on the Pi 3 A+, the USB uplink and a USB GPS receiver compete for
  the single port; the BOM recommends a Bluetooth OBD-II adapter for that
  reason.

---

## 4. Car library coverage (bundled data)

Generated with `tools/car_library/car_library_stats.py` through the runtime
loader `load_vehicle_configurations()`. Re-run it before and after library data
changes and update this table.

| Metric | Value |
|---|---|
| Brands | Audi (210 rows), BMW (368 rows); market EU only |
| Exact configuration rows | 578 (ICE 518, PHEV 32, EV 28) |
| Picker models / generation codes / variants | 93 / 71 / 465 |
| Production years | 2008–2026 |
| Rows with tire options | 577 (1 has the default only) |
| Rows with driven final drive | 512 (89%); 66 without: Audi 8X 3, 8V 2, 8Y 4, B8 9, B9 3, C7 4, C8 3, D4 2, J1 4, GA 4, 8U 8, FZ 4, 8R 4, 4S 2, 8J 4, 8S 3; BMW I20 1, F48 1, F39 1 (each carries an `unresolved` final-drive note) |
| Rows with top gear | 502 of 550 non-EV rows (91%); the 28 EVs have none: the reduction ratio is the final drive; 48 non-EV rows without, each with an `unresolved` top-gear note |
| Rows with full gear sets | 360 (62%) |
| Tire confidence | official_exact 423 · reputable_secondary 42 · official_derived 7 · family_default 74 · unverified 32 |
| Driven final-drive confidence | official_exact 320 · official_derived 100 · reputable_secondary 22 · family_default 37 · unverified 33 · none 66 |
| Top-gear confidence | official_exact 394 · official_derived 15 · reputable_secondary 26 · family_default 38 · unverified 29 · none 76 (28 EVs, 48 unsourced) |
| Weak (family_default or unverified) | final drive 70/578 (12%), top gear 67/578 (12%), tire 106/578 (18%) |
| `order_reference_trust` | trusted 460 · approximate 77 · backlog_unverified 41 |
| `requires_manual_confirmation` | true 70, false 508 (true exactly when the driven final drive or top gear is weak) |
| Picker variants without any gearbox | 0 |
| Variants whose rows differ in tire options | 20 (the picker offers the union) |
| Model families split into several picker entries by year label | 0 (one entry per generation) |

**How confidence is surfaced today:**

- Per-field confidence shows as a chip on each gearbox option, on each value
  in the specs form and on each saved car's row (`provenanceTier` in
  `apps/ui/src/car_references.ts`).
- A weak final drive or top gear adds what it does to the result ("driveline
  results will be marked as estimated") to the wizard hint and the car row,
  with "Edit the car if you know the exact figures"
  (`estimateNoteKey` in `apps/ui/src/pages/cars/wizard_model.ts`).
- The status is stored on the car and copied into run metadata
  (`apps/server/vibesensor/recording/run_metadata_builder.py`). Analysis
  reads it: a weak final drive or top gear hedges the source checks to
  `ruled_out_estimated`, and the diagnosis `conditions` carry each
  reference's provenance. The powertrain (`fuel_type`, from the library or
  asked in the wizard) is kept on the car, the run and `conditions`, and
  decides how the engine is checked (§5.3).

**What could be prefilled but isn't** (data gaps; WP5 in
[user_journey_gaps.md](user_journey_gaps.md)):

- **Bodies:** 3 and 5 Series Touring exist (F31, G21; F11, G31, G61). Audi
  estates exist for the A4 Avant (B9 facelift), A6 Avant (C8), RS 4 Avant and
  RS 6 Avant; the older A4/A6 generations (B8, C7) have none, and estate cars
  are a large share of the EU fleet. The A5 (B9 facelift) has Coupé,
  Sportback and Cabriolet rows.
- **Generations:** none before ~2011 (no E90/E60/E84/E70, no Audi B7/8P/C6).
- **Model years:** several generations only have launch-year rows (F20
  2011–2012, G11 2016, F15 2014–2015). The picker takes a generation's years
  from its rows, so a 2015 F20 owner still sees "1 Series (F20, 2011-2012)".
  F10 and G30 now span 2011–2016 and 2017–2023, with a separate row per
  final-drive change.
- **Final drive:** missing on the rows counted in the table above. The
  `unresolved` notes say the manufacturer publishes split, conflicting or no
  values (the Q4 e-tron sheets from 2024 on and the facelifted e-tron GT
  sheets print no reduction ratio); do not invent one. Weak
  (family_default or unverified) on 70 rows. Those rows are where a single
  parts-catalogue lookup per transmission code upgrades many rows at once.

---

## 5. Capability matrix

What the software can diagnose, by what the user has. The tables are the
intended behaviour; deviations today are listed under each table with a gap id.

Legend:

- **✓** — tested: a "ruled out" or a finding is meaningful.
- **~** — tested with a caveat that must be printed.
- **✗** — couldn't test, with a reason.

### 5.1 References × speed source

| Tire | Final drive | Top gear | Speed source | Wheel/tire | Driveline | Engine |
|---|---|---|---|---|---|---|
| no | – | – | GPS | ✗ no tire size | ✗ | ✗ |
| no | – | – | OBD-II | ✗ no tire size | ✗ | ✓ measured RPM |
| yes | no | no | GPS | ✓ | ✗ no final drive | ✗ no RPM/gear |
| yes | no | no | OBD-II | ✓ | ✗ no final drive | ✓ measured RPM |
| yes | library, weak confidence | library, weak | GPS | ✓ | ~ "estimated final drive" | ~ "estimated ratios; RPM estimated, top gear only" |
| yes | yes (user or library-strong) | no | GPS | ✓ | ✓ | ✗ no gear ratio |
| yes | yes | yes | GPS | ✓ | ✓ | ~ "RPM estimated assuming top gear" |
| yes | yes | yes | OBD-II | ✓ | ✓ | ✓ measured RPM |
| any | any | any | Manual (fixed) | ~ a found cause is hedged; never ruled out | ~ same | ~ same |

**Today:**

- **Manual entry**, **library-estimate row** and **manual speed:** the car
  wizard and car list ("This car can test"), analysis, the report, History and
  the Live capability line match the table.

### 5.2 Sensor layout

| Layout | Source type | Location |
|---|---|---|
| One sensor (anywhere) | ~ source type (wheel/driveline/engine), with `single_sensor` as the weak reason (`_weak_reasons` in `diagnosis.py`) | ✗ |
| Cabin only (seat/trunk) | ✓ | wheel/tire: `history.zone.unlocated_wheel` "No single wheel; strongest at {location}" |
| One wheel + cabin | ✓ | ~ that wheel's corner, never its axle (`_zone` in `diagnosis.py`) |
| Four wheels (± cabin) | ✓ | ✓ corner / axle / all four; all four gets the neutral coast check, not an axle swap (`_confirm_check` in `view_model.py`) |
| Engine bay / tunnel / transmission sensors | ✓ | ✓ driveline/engine zone (`_zone`) |

**Today:** as the table; the Sensors tab's mounting panel and the Live
capability line state the current layout's consequence.

### 5.3 Vehicle type

| Type | Wheel/tire | Driveline | "Engine" | Guided coast-down |
|---|---|---|---|---|
| ICE manual/automatic | per §5.1 | per §5.1 | per §5.1 (top gear / D) | valid |
| EV (single speed) | per §5.1 | motor-to-wheel reduction acts as the final drive | should read "motor order"; the motor stays coupled | invalid: neutral does not decouple the motor |
| PHEV/hybrid | per §5.1 | per §5.1 | ~ the engine may be off; RPM estimate is unreliable | ~ |

**Today:**

- **EV:** the engine check is `not_applicable` (reason `electric_car`), never
  "couldn't test" or "ruled out". The driveline order (wheel speed ×
  reduction ratio) is the motor's 1× and 2×, so that family is worded
  "Electric motor" in the report, History, the car wizard, the Live
  capability line and the spectrum. An EV has no top gear: library EV rows
  carry none and a saved EV car keeps none, so nothing (confirmation, the
  motor check, an RPM estimate) depends on one. The Audi e-tron GT's rear
  motor has a 2-speed gearbox; the library stores its official second-gear
  ratio (8.2:1), the gear the car normally drives in, as the one rear
  reduction ratio. In first gear (15.6:1: launch starts, or held in the
  dynamic driving mode) the rear motor turns 1.9 times faster, at an order
  the analysis does not model. The coast-down judges nothing
  (`speed_dependence` stays `null`), no engine markers are drawn, and the
  confirm step is a repeat drive instead of a neutral coast. The report's
  test conditions print "Powertrain: electric (EV)" and say plainly that the
  motor's electrical and gear-mesh orders are not analysed
  (`_source_checks`, `_order_markers` in `diagnosis.py`; `_conditions`,
  `_Ctx.source_key` in `report/view_model.py`). Readiness reports the engine
  as `not_applicable` and an EV on OBD-II speed does not wait for RPM
  (`capture_readiness_evaluator.py`).
- **PHEV:** without OBD-II RPM, an engine no-match is `ruled_out_estimated`
  with reason `engine_may_be_off` ("not conclusive"), and readiness says
  `hybrid_estimated`. With OBD-II, a measured 0 rpm means the engine was off
  (it is never replaced by an estimate), and if the engine ran for less than
  35% of the measured samples the engine check is `not_testable` with reason
  `engine_not_running` (`_rpm_readings` in `diagnosis.py`,
  `_effective_engine_rpm` in `_reference_resolution.py`). On a combustion car
  (or an unknown powertrain) a 0 rpm reading while driving is a bad reading,
  not an engine off: the RPM is estimated from speed as without OBD-II, and no
  hybrid wording is used.

# Car library architecture

`apps/server/vibesensor/data/vehicle_configurations/**/*.json` is the canonical
runtime source for car ratio and tire data.

Each shard file is a canonical JSON object with optional shard-local
`definitions` and a required `configurations` array of exact
vehicle-configuration rows, grouped by brand, model family, and
generation/body code:

- `vehicle_configurations/<brand>/<model_family>/<generation_or_body_code>.json`
- example: `vehicle_configurations/bmw/5_series/G30.json`

Shard shape (top-level keys: optional `definitions`, optional
`defaults`, required `configurations`):

```json
{
  "definitions": {
    "notes": {"n1": "<repeated note>"},
    "evidence_ref_sets": {"e1": ["source_pack:source-id"]},
    "tire_setups": {
      "standard_18": {
        "confidence": "official_exact",
        "front": {"width_mm": 225, "aspect_pct": 45, "rim_in": 18},
        "rear":  {"width_mm": 255, "aspect_pct": 40, "rim_in": 18},
        "default_axle_for_speed": "rear",
        "evidence_refs_ref": "e1"
      }
    }
  },
  "defaults": {"brand": "BMW", "model_code": "G20"},
  "configurations": [{"id": "...", "tires": {"default_ref": "standard_18"}}]
}
```

A row references shard-local definitions like this:

```json
{
  "drivetrain": {"confidence": "...", "value": "RWD",
                 "notes_ref": "n1", "evidence_refs_ref": "e1"},
  "tires": {
    "default_ref": "standard_18",
    "options": [{"name": "Sport 19", "setup_ref": "standard_18"}]
  }
}
```

`definitions` is optional; if omitted, all field metadata is inline.
Field metadata (`drivetrain`, `transmission`, `ratios.*`, `tires.*`, etc.)
may use `notes_ref` instead of inline `notes`, and `evidence_refs_ref`
instead of inline `evidence_refs`. Verification-note rows may also use
`note_ref`. Tire setups can be lifted into `definitions.tire_setups`
and referenced from rows via `tires.default_ref` (full default block)
and from option entries via `setup_ref` (option keeps its `name` and
may override individual setup keys; the lifted setup keys merge in
without overwriting). The loader expands every ref into its inline form
before strict shape validation. Unknown refs fail closed.

`defaults` is also optional. When present, every key in `defaults` is
shallow-merged into each row before strict validation, so rows can omit
fields that are uniform across the shard (`brand`, `type`, `market`,
`model_code`, `body_code`, `model_name`, production years). Row-level
keys override the default for that row only. Required fields that are
still missing after the merge fail closed; unknown shard top-level keys
also fail closed.

Definitions are kept shard-local on purpose: a single generation file
remains understandable without jumping to a global metadata file.

### Note hygiene

Field-level `notes` and verification-note rows are reserved for
information specific to the vehicle configuration: source caveats,
unresolved research details, or per-variant evidence nuance. Generic
migration provenance (e.g. "Migrated from legacy grouped car-library
data ...", "<field>: confidence was 'no_confidence' ... remapped to
'unverified' for schema compliance.", "Legacy variant-source research
previously recorded this variant as ...") is intentionally not stored
inline. That history is documented here in this file, not on every
field.

The canonical rows under `vehicle_configurations/` were originally
imported from the legacy grouped car library. During import, fields
without authoritative provenance were given `unverified` confidence and
the original `no_confidence` remap was recorded in per-field notes. Once
the canonical loader and validators stabilized, those migration notes
were removed during the canonical-loader migration. New rows must not
re-introduce migration boilerplate at the field level; if a value is
inherited from family-level data, encode that through `confidence` and
`evidence_refs`, not through prose.

### Data conventions

- **Model years:** a row covers every model year in which its gearbox, top
  gear and final drive stay the same. When an official sheet changes one of
  them, the new state gets its own row; a later standard tyre is added as a
  tyre option instead. A new state starts as follows: a change valid from
  January–July counts from that year, a later one from the next year, and the
  exact validity month goes in a verification note. Rows of one variant with
  the same gearbox name must not overlap in years (the picker offers one
  entry per model-year period).
- **Bodies:** an estate body is its own model with its own generation code,
  e.g. `5 Series Touring (G31, 2017-2023)` with `type` `Wagon`, because the
  manufacturer's sheets give it its own tyres and sometimes its own final
  drive.
- **AWD axle ratios:** when the sheet publishes one axle ratio for an
  all-wheel-drive car, the row stores it as `final_drive_rear` only; the
  front ratio is not invented or copied. Both fields are set only when the
  sheet lists separate front and rear ratios (electric cars with one motor
  per axle). A plug-in hybrid whose engine drives only the front axle, with
  an electric motor on the rear axle, stores the gearbox final drive as
  `final_drive_front`. The validator rejects a non-EV AWD row whose front
  and rear values are equal (`drivetrain_final_drive_layout`).
  The picker serves each gearbox's driven final drive with the axle it
  belongs to (`final_drive_axle`, from
  `VehicleConfiguration.driven_final_drive_axle`): `front` for FWD and for
  an e-AWD hybrid (front only), `rear` for RWD and for an AWD row with both
  ratios (the rear motor's or rear differential's), and `null` for an AWD
  row with one published axle ratio, which does not say which axle it is.
- **Staggered tyres:** a tyre setup stores a `rear` size next to `front` when
  the sheet or price list prints a mixed set (e.g. G32 245/45 R19 front with
  275/40 R19 rear); options carry the sizes as printed. The order analysis
  places a wheel sensor's wheel orders (T1, T2, and the spectrum's markers)
  on its own axle's tyre (`AxleTireSetup.axle_tire_circumference_m`); every
  other sensor's wheel orders, and the propshaft and engine orders, use the
  circumference `default_axle_for_speed` picks
  (`AxleTireSetup.effective_tire_circumference_m`). Rows set `rear`, the
  driven axle of a rear-wheel-drive car and xDrive's main-drive axle. The two
  diameters of BMW's mixed sets differ by about 0.1–0.7 %; the benchmark's
  staggered coupe (`bench-*-staggered-tires-sweep`) runs 3 % apart.
- **Drive layout on a saved car:** a car added from the library takes the
  variant's `drivetrain` as its drive layout and the gearbox's
  `final_drive_axle` (which axle the engine drives), kept while the layout
  is, also when the owner corrects or clears the ratio. Cars saved before the
  layout existed get it on load from the rows they were picked from (same
  body type and variant, preferring rows whose `"{brand} {model} {variant}"`
  is the car's name; a variant saved before it was split by model year
  matches without the years; a name that starts with a library generation's
  brand, model and generation code, such as a pre-#4153 label
  `"BMW 1 Series (F40, 2019-2024) 118i"`, matches only that generation's
  rows, so a variant name another generation shares never lends its layout)
  when those rows agree on one layout, with the gearbox's axle, and are
  saved again (`with_library_fields` in
  `apps/server/vibesensor/settings/car_library.py`). Cars saved before the
  powertrain (`fuel_type`) existed get it the same way, so the report's
  "Powertrain" fact does not read "not provided" for a library car. Cars
  saved before the engine profile existed get it the same way (from rows
  that agree on one; never for an EV). A car the
  library does not know keeps no layout, powertrain or engine (unknown). See `apps/server/vibesensor/domain/drive_layout.py`
  for what the layout decides: the driven axles and whether there is a
  propshaft (none for FWD, an EV or an e-AWD hybrid; front-engined cars
  assumed). A dual-motor EV is AWD with the rear motor's reduction ratio; the
  front motor's order is not analysed.
- **Engine text:** `engine_name` reads `<family code> <litres>L <layout>
  [Turbo|Supercharged] [Diesel] [PHEV]`, e.g. `B47 2.0L I4 Turbo Diesel` or
  `3.0L V6 Supercharged` (Audi's mechanically supercharged 3.0 TFSI).
  Litres, layout, charging and fuel come from the technical-data sheet; the
  family code is left out when it is not known for the row. All rows of one generation use the
  same text for the same engine. EVs use `Electric Single Motor` /
  `Electric Dual Motor`. The layout token is the engine's evidence-backed
  profile: `VehicleConfiguration.engine_profile` reads `I6` as an inline-6
  and `V8` as a V8 (`domain/engine_profile.py`), and each picker variant
  serves it as `engine_profile` when its rows agree; EVs have none. The bank
  angle is not on the sheets, so library profiles leave it unknown. The
  analysis, report and live bands use the profile's engine orders (an
  inline-6's E1 and E3); see docs/order_tracking.md "Engine orders".
  `engine_code` repeats the family code, or reads
  `<litres>L` (`Electric` for EVs) when there is none. The validator
  enforces the format, the code and the fuel type (`PHEV` text ⇔ fuel type
  `PHEV`, `Electric` ⇔ `EV`) for the brands listed in `ENGINE_TEXT_BRANDS`
  (`tools/car_library/car_library_validation/_powertrain.py`); a brand joins
  that list once its rows follow the format.
- **Dual-clutch output final drives:** some dual-clutch sheets print two
  final drives (Audi: "final drive ratio 1-2 / 2-3"), one per gearbox output
  shaft. They are not front and rear axle ratios. A row stores the one behind
  the top gear in the driven axle field only when the sheet's forward ratios
  show which one that is; otherwise it stores neither and records an
  `unresolved` note.
- **Manual gearboxes with a second final drive:** the same rule applies to a
  manual with two output shafts. BMW's sheets for the X1/X2 xDrive18d six-speed
  manual print one final drive (4.059) but, from 07/2019, overall ratios
  (gear × final drive) whose gears V–VI do not match it. The row stores the
  final drive behind the top gear, derived as overall top ratio ÷ top-gear
  ratio (`official_derived`), and an `unresolved` note says the gears I–IV
  final drive is not modelled. A sheet that prints only per-gear ratios and
  one final drive is stored as printed; a row whose gear set matches a known
  split gearbox gets an `unresolved` note instead of a guessed second value.

Each row represents one exact vehicle configuration and keeps the qualified
order-analysis fields inline with their own metadata:

- drivetrain, transmission, top-gear ratio, gear ratios, final-drive ratios,
  and tire setup values live next to their confidence, evidence refs,
  verification notes, and unresolved items
- `configuration_confidence` summarizes whole-row confidence
- whether a gearbox asks the user to confirm its ratios
  (`requires_manual_confirmation`) is derived from the row: true exactly when
  the driven final drive or the top gear is `family_default` or `unverified`
  (`VehicleConfiguration.requires_manual_drivetrain_confirmation`). A missing
  final drive or top gear is "couldn't test", not a value to confirm.
- the driven final drive and `ratios.top_gear_ratio` are optional: leave a
  value out rather than enter a weak or unsourced one. A row without one must
  carry an `unresolved` item naming it and saying why; the validator enforces
  this (`drivetrain_final_drive_layout`, `missing_top_gear`). Both rules read
  the item the same way: spaced, hyphenated or as the field name ("Final
  drive", "final-drive", "final_drive_ratio"; likewise "top gear"). The picker
  serves the missing ratio as `null`, the
  wizard shows it as unknown and saves the car without it, and the analysis
  reports the checks that need it as not testable: without a top gear the
  engine is checked only from measured OBD-II RPM; wheel and driveline checks
  are unaffected. Rows carry no per-row policy flags.
- an EV row (`fuel_type: EV`) has no `ratios.top_gear_ratio` and needs no
  `unresolved` item for it: a single-speed EV has no gearbox to research, its
  motor-to-wheel reduction ratio is the final drive, and the motor is checked
  at wheel speed × reduction ratio. The validator rejects a stored one
  (`ev_top_gear`), so an EV's confirmation and research completeness follow
  its reduction ratio alone, and a saved EV car keeps no top gear either
  (`Car`). The Audi e-tron GT's rear motor has a 2-speed gearbox
  (transmission code `AT2`); its pre-facelift rows store the official
  second-gear ratio (8.2:1) as the one rear reduction ratio, the gear the car
  normally drives in, and an `unresolved` item records that first gear
  (15.6:1) is not encoded. Audi publishes no ratio for the facelift, so those
  rows have no final drive.

`tools/car_library/car_library_validation/data/car_sources/*.json` contains only reusable
source-document metadata. It is test-only data and does not ship in the wheel. `evidence_refs` inside canonical rows resolve through
those source packs.

## Runtime model

Runtime code loads canonical rows through
`vibesensor.settings.vehicle_configurations.load_vehicle_configurations()`.
Grouped picker payloads are derived at runtime in
`vibesensor.settings.car_library` by grouping exact configurations by
brand, type, model generation, and variant:

- **Model:** one picker entry per generation. Rows group by brand, type,
  the model name without its trailing `(code, years)` label, and
  `model_code`. The entry is labelled with the code and the generation's
  model years taken from the rows' production years, e.g.
  `X1 (F48, 2015–2022)`. Each row's `model_name` uses the same
  `Base (CODE, first-last)` form (one year when the rows cover one model
  year); a row whose label carries other years still lands in the same
  entry, since the label is rebuilt from the rows.
- **Variant:** one picker entry per `variant_name`, carrying its
  `production_start_year` / `production_end_year`. When two of a variant's
  rows share a gearbox name (an xDrive25d sold in 2015–2020 and again in
  2021–2022 with another final drive), the model year decides the row: the variant is
  offered once per model-year period, named with its years
  (`xDrive25d (2021–2022)`). A row whose years span several periods appears in
  each.
- **Gearbox:** every exact row is one gearbox option, and a picker variant
  never lists a gearbox name twice, so (model, variant, gearbox) names
  exactly one row. The picker build keeps each variant's rows
  (`_ROWS_BY_VARIANT` in `vibesensor/settings/car_library.py`), and
  `apps/server/tests/settings/test_car_library.py` checks that every bundled
  row is reachable this way.

Saved cars keep a copy of the chosen values and the variant name; they are
never re-resolved against the library, so regrouping the picker does not
change an existing car.

That means:

1. no committed grouped-truth data file backs the picker
2. no split provenance/evidence ledger backs ratio or tire fields
3. numeric order-analysis consumers read normalized values from canonical exact
   rows, not from model-family defaults

A picker variant offers the union of its rows' tire options, one option per
tire size (front and rear). When several rows list the same size, the option
with the best source confidence wins.

Every exact row becomes a picker gearbox option. Rows may leave the final
drive unresolved on purpose (the manufacturer publishes none, or publishes
split final-drive values that the single `final_drive_front`/`final_drive_rear`
fields cannot encode faithfully; see the row's `unresolved` items). Such a
gearbox is served with `final_drive_ratio: null` and no final-drive
confidence; the UI shows the final drive as unknown, the car is saved without
one, and the driveline order reports "not testable". Do not invent a final
drive. `apps/server/tests/web/test_car_library_bundled_contract.py`
checks that every bundled brand/type/model passes the HTTP response models.

## Confidence vocabulary

Field-level confidence values:

- `official_exact`
- `official_derived`
- `reputable_secondary_crosschecked`
- `family_default`
- `unverified`
- `user_confirmed` for saved-car overrides

Configuration-level confidence values:

- `high_confidence`
- `medium_confidence`
- `low_confidence`
- `no_confidence`
- `not_applicable`

## Coverage classifications

`VehicleConfiguration` exposes two distinct coverage signals so callers can
ask the right question:

- `research_completeness` reflects broad row research quality across all
  documented fields, including non-math labels such as `transmission_name`
  and `drivetrain`. It is what the row looks like to a maintainer reviewing
  research progress.
- `order_reference_trust` (and `order_reference_trust_for(kind)`) reflects
  trust in the actual runtime math inputs only:

  - `wheel_order`  → tire dimensions
  - `driveshaft_order`  → tire dimensions + selected final-drive ratio
  - `engine_order`  → tire dimensions + selected final-drive ratio + top-gear
    ratio

Order-analysis consumers should use `order_reference_trust` so weak
documentation on non-math fields does not artificially demote a row whose
math inputs are evidence-backed.

## Validation

At runtime the loader (`vibesensor.settings.vehicle_configurations`)
only schema-checks rows and resolves shard refs. The cross-field plausibility
and source-evidence rules gate the bundled data in the test suite instead of
running at app startup:

- `tools/car_library/car_library_validation/` is the validation
  facade. Its submodules split allowlists, legacy grouped rows, exact-row
  checks, powertrain rules, tire rules, and duplicate detection.
- `tools/car_library/car_library_validation/source_evidence.py`
  resolves `evidence_refs` against `data/car_sources/*.json`.
- `test_bundled_vehicle_library_passes_validation` in
  `apps/server/tests/settings/test_car_library_validation.py`
  runs both against the packaged shards, so bad data fails CI rather than
  silently emptying the library on the device. Run the same check directly
  while editing shards with `python tools/car_library/validate_vehicle_library.py`.
- `python tools/car_library/car_library_stats.py` prints the coverage numbers
  behind the table in `docs/user_journeys.md` §4; re-run it after data changes.

The bundled grouped picker is a projection only. Canonical exact-row shards
remain the single source of truth.

## Shard JSON Schema

`tools/car_library/car_library_validation/data/vehicle_configuration_shard.schema.json`
is the canonical JSON Schema (Draft 2020-12) for shard files under
`apps/server/vibesensor/data/vehicle_configurations/**/*.json`. It validates
the raw on-disk shape, including the `definitions` / `defaults` /
`configurations` blocks and the supported ref forms (`notes_ref`, `note_ref`,
`evidence_refs_ref`, `default_ref`, `setup_ref`).

The schema is an editor aid and is not enforced in CI; the enforced contract
is the backend loader. `apps/server/tests/settings/test_vehicle_configurations.py`
loads every committed shard through it and checks representative invalid
cases. Run it with the rest of the persistence suite:

```bash
pytest -q apps/server/tests/settings/test_vehicle_configurations.py
```

To get inline validation while editing shards, point your editor at the
schema file. Example VS Code setting:

```json
{
  "json.schemas": [
    {
      "fileMatch": [
        "apps/server/vibesensor/data/vehicle_configurations/**/*.json"
      ],
      "url": "./tools/car_library/car_library_validation/data/vehicle_configuration_shard.schema.json"
    }
  ]
}
```

Schema validation and the backend loader are kept in sync. When the loader
contract changes, update both at once.

## Duplicate detection

`validate_vehicle_configurations` (in
`tools/car_library/car_library_validation`) flags duplicate
and near-duplicate exact rows after the per-row checks:

- `duplicate_vehicle_configuration` (hard failure): two or more rows share
  the same normalized identity (brand, model, variant, drivetrain, fuel
  type, transmission, top gear, final drives, default tire signature).
- `near_duplicate_vehicle_configuration` (advisory): two or more rows share
  the same fuzzy label key (brand + model + variant after stripping case,
  punctuation, and whitespace) but have different math identity. The row
  IDs of the colliding peers are listed in the message.

Both rules go through the existing
`tools/car_library/car_library_validation/data/allowlist.json`. To
keep an intentional duplicate or label collision, add an entry with the
rule name, the offending row `id`, and a `reason`.

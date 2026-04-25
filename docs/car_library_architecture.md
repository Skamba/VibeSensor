# Car library architecture

The legacy car library in `apps/server/vibesensor/data/car_library.json` is
still the compatibility source for the current API/UI picker: brand, type,
model, and variant selection continue to flow through the existing
model-plus-variant shapes.

For drivetrain and order-analysis accuracy, that legacy structure is **not**
the source of truth anymore when an exact row exists. Broad model defaults plus
optional variant overrides are convenient for the picker, but they can silently
inherit a gearbox or final-drive assumption that does not belong to the exact
configuration under analysis.

`apps/server/vibesensor/data/vehicle_configurations.json` is the new exact-row
source of truth for the migrated subset. Each row names one exact drivetrain
configuration with:

- vehicle identity fields such as market, model/body code, production range,
  model name, and variant name
- drivetrain, transmission, final-drive, and fuel-type facts
- field-level provenance and confidence for the accuracy-critical fields that
  drive order analysis
- the default tire plus available tire options
- `source_status` so callers can tell exact rows from compatibility projection

Current migration policy:

1. Prefer exact configuration rows when they exist for the selected variant.
2. Fall back to a compatibility projection from the legacy model/variant entry
   only when no exact row exists yet.
3. Keep the fallback explicit: one projected row per gearbox, so broad
   inheritance does not stay hidden.
4. Keep provenance inline with the exact row so values and source/confidence
   metadata cannot drift into separate ledgers.

Issue #3229 starts this migration with a small BMW subset:

- `4 Series (G22, 2021-2026) / 420i` for an exact ICE RWD row
- `2 Series Active Tourer (F45, 2014-2021) / 220i` and `225xe` for exact
  FWD/PHEV override rows
- `3 Series (G20, 2019-2025) / 330i xDrive` for an exact AWD/xDrive row
- `5 Series (G60, 2024-2026) / i5 eDrive40` for an exact EV single-speed row

This is intentionally additive. The legacy picker payloads stay stable while
diagnosis-facing code gains a typed exact-row path that can expand model by
model without a full one-shot database rewrite.

## Field-level provenance and confidence

`VehicleConfiguration.field_provenance` is the machine-readable source metadata
for the fields that most directly affect order analysis:

- `final_drive_front`
- `final_drive_rear`
- `top_gear_ratio`
- `gear_ratios`
- `drivetrain`
- `tire_dimensions`

Each provenance entry stores:

- the field name
- the confidence level
- an optional `source_id`
- an optional `verified_at`
- optional notes

### Confidence levels

- `official_exact`: official manufacturer source directly confirms the exact
  stored field value
- `official_derived`: the stored value is derived from official manufacturer
  data (for example a fixed EV single-speed ratio projected to `1.0`)
- `reputable_secondary_crosschecked`: non-official technical references were
  cross-checked and kept because the official source only confirmed part of the
  story
- `family_default`: the field still follows the supported family baseline until
  a variant-specific source is captured
- `unverified`: the stored value is still present but should not be treated as a
  verified source-of-truth fact
- `user_confirmed`: reserved for future locally confirmed overrides

### Source ID prefixes

`source_id` stays lightweight and links back to the existing research trail:

- `ratio_sources:<CAR_KEY>:<SOURCE_GROUP>` points at a source group in
  `apps/server/vibesensor/data/car_library_ratio_sources.json`
- `variant_sources:<CAR_KEY>:<VARIANT_NAME>` points at the variant table in
  `apps/server/vibesensor/data/CAR_VARIANT_SOURCES.md`

That keeps the old research notes intact instead of copying them into the exact
rows.

### Validation and analysis-confidence policy

Rows marked `official_exact` must include a `source_id`; loader validation
rejects exact-row data that breaks that rule.

The confidence levels are the source data for future analysis-confidence
policies:

- `official_exact` and `official_derived` are the highest-confidence rows
- `reputable_secondary_crosschecked` is usable but should rank below official
  evidence
- `family_default` and `unverified` are compatibility data and should lower
  downstream confidence when order-analysis logic consumes them

Issue #3231 starts this provenance path with representative BMW exact rows for:

- `2 Series Active Tourer (F45, 2014-2021) / 220i`
- `2 Series Active Tourer (F45, 2014-2021) / 225xe`
- `3 Series (G20, 2019-2025) / 330i xDrive`
- `5 Series (G60, 2024-2026) / i5 eDrive40`

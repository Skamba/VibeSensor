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
- the default tire plus available tire options
- `source_status` so callers can tell exact rows from compatibility projection

Current migration policy:

1. Prefer exact configuration rows when they exist for the selected variant.
2. Fall back to a compatibility projection from the legacy model/variant entry
   only when no exact row exists yet.
3. Keep the fallback explicit: one projected row per gearbox, so broad
   inheritance does not stay hidden.

Issue #3229 starts this migration with a small BMW subset:

- `4 Series (G22, 2021-2026) / 420i` for an exact ICE RWD row
- `2 Series Active Tourer (F45, 2014-2021) / 220i` and `225xe` for exact
  FWD/PHEV override rows
- `3 Series (G20, 2019-2025) / 330i xDrive` for an exact AWD/xDrive row
- `5 Series (G60, 2024-2026) / i5 eDrive40` for an exact EV single-speed row

This is intentionally additive. The legacy picker payloads stay stable while
diagnosis-facing code gains a typed exact-row path that can expand model by
model without a full one-shot database rewrite.

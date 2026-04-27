# Car library architecture

`apps/server/vibesensor/data/vehicle_configurations/**/*.json` is the canonical
runtime source for car ratio and tire data.

Each shard file is a canonical JSON array of exact vehicle-configuration rows,
grouped by brand, model family, and generation/body code:

- `vehicle_configurations/<brand>/<model_family>/<generation_or_body_code>.json`
- example: `vehicle_configurations/bmw/5_series/G30.json`

Each row represents one exact vehicle configuration and keeps the qualified
order-analysis fields inline with their own metadata:

- drivetrain, transmission, top-gear ratio, gear ratios, final-drive ratios,
  and tire setup values live next to their confidence, evidence refs,
  verification notes, and unresolved items
- `configuration_confidence` summarizes whole-row confidence
- `order_analysis_policy` states whether the row is usable for engine,
  driveshaft, and wheel-order analysis and whether manual confirmation is still
  required

`apps/server/vibesensor/data/car_sources/*.json` now contains only reusable
source-document metadata. `evidence_refs` inside canonical rows resolve through
those source packs.

## Runtime model

Runtime code loads canonical rows through
`vibesensor.adapters.persistence.vehicle_configurations.load_vehicle_configurations()`.
Grouped picker payloads are derived at runtime in
`vibesensor.adapters.persistence.car_library` by grouping exact configurations by
brand, type, model, and variant.

That means:

1. no committed grouped-truth data file backs the picker
2. no split provenance/evidence ledger backs ratio or tire fields
3. numeric order-analysis consumers read normalized values from canonical exact
   rows, not from model-family defaults

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

## Validation

Canonical validation lives in:

- `vibesensor.adapters.persistence.car_library_validation` for structural and
  plausibility checks on canonical configs and derived picker rows
- `vibesensor.adapters.persistence.car_library_source_evidence` for
  `evidence_refs` resolution against `car_sources/*.json`

The bundled grouped picker is a projection only. Canonical exact-row shard arrays
remain the single source of truth.

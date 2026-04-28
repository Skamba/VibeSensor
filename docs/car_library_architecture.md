# Car library architecture

`apps/server/vibesensor/data/vehicle_configurations/**/*.json` is the canonical
runtime source for car ratio and tire data.

Each shard file is a canonical JSON object with optional shard-local
`definitions` and a required `configurations` array of exact
vehicle-configuration rows, grouped by brand, model family, and
generation/body code:

- `vehicle_configurations/<brand>/<model_family>/<generation_or_body_code>.json`
- example: `vehicle_configurations/bmw/5_series/G30.json`

Shard shape:

```json
{
  "definitions": {
    "notes": {"n1": "<repeated note text>"},
    "evidence_ref_sets": {"e1": ["source_pack:source-id", "..."]}
  },
  "defaults": {
    "brand": "BMW",
    "type": "sedan",
    "market": "EU",
    "model_code": "G20",
    "body_code": "G20",
    "model_name": "3 Series (G20, 2018-2024)"
  },
  "configurations": [
    {
      "id": "...",
      "drivetrain": {
        "confidence": "...",
        "value": "RWD",
        "notes_ref": "n1",
        "evidence_refs_ref": "e1"
      }
    }
  ]
}
```

`definitions` is optional; if omitted, all field metadata is inline.
Field metadata (`drivetrain`, `transmission`, `ratios.*`, `tires.*`, etc.)
may use `notes_ref` instead of inline `notes`, and `evidence_refs_ref`
instead of inline `evidence_refs`. Verification-note rows may also use
`note_ref`. The loader expands every ref into its inline form before
strict shape validation. Unknown refs fail closed.

`defaults` is also optional. When present, every key in `defaults` is
shallow-merged into each row before strict validation, so rows can omit
fields that are uniform across the shard (`brand`, `type`, `market`,
`model_code`, `body_code`, `model_name`, production years). Row-level
keys override the default for that row only. Required fields that are
still missing after the merge fail closed; unknown shard top-level keys
also fail closed.

Definitions are kept shard-local on purpose: a single generation file
remains understandable without jumping to a global metadata file.

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

Canonical validation lives in:

- `vibesensor.adapters.persistence.car_library_validation` for structural and
  plausibility checks on canonical configs and derived picker rows
- `vibesensor.adapters.persistence.car_library_source_evidence` for
  `evidence_refs` resolution against `car_sources/*.json`

The bundled grouped picker is a projection only. Canonical exact-row shards
remain the single source of truth.

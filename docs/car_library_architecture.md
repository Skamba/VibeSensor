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

Each row represents one exact vehicle configuration and keeps the qualified
order-analysis fields inline with their own metadata:

- drivetrain, transmission, top-gear ratio, gear ratios, final-drive ratios,
  and tire setup values live next to their confidence, evidence refs,
  verification notes, and unresolved items
- `configuration_confidence` summarizes whole-row confidence
- the order-analysis policy is derived at load time from the row math inputs
  (top-gear ratio, driven final-drive, drivetrain) by
  `derive_order_analysis_policy`. Rows that need to deviate from the derivation
  carry a sparse `order_analysis_policy_override` block with an explicit
  `reason` and only the differing flags. Rows that match the derivation omit
  the block entirely.

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

## Shard JSON Schema

`apps/server/vibesensor/data/schema/vehicle_configuration_shard.schema.json`
is the canonical JSON Schema (Draft 2020-12) for shard files under
`apps/server/vibesensor/data/vehicle_configurations/**/*.json`. It validates
the raw on-disk shape, including the `definitions` / `defaults` /
`configurations` blocks and the supported ref forms (`notes_ref`, `note_ref`,
`evidence_refs_ref`, `default_ref`, `setup_ref`).

`apps/server/tests/adapters/persistence/test_vehicle_configuration_shard_schema.py`
runs the schema against every committed shard and checks representative
invalid cases. Run it with the rest of the persistence suite:

```bash
pytest -q apps/server/tests/adapters/persistence/test_vehicle_configuration_shard_schema.py
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
      "url": "./apps/server/vibesensor/data/schema/vehicle_configuration_shard.schema.json"
    }
  ]
}
```

Schema validation and the backend loader are kept in sync. When the loader
contract changes, update both at once.

## Duplicate detection

`validate_vehicle_configurations` (in
`vibesensor.adapters.persistence.car_library_validation`) flags duplicate
and near-duplicate exact rows after the per-row checks:

- `duplicate_vehicle_configuration` (hard failure): two or more rows share
  the same normalized identity (brand, model, variant, drivetrain, fuel
  type, transmission, top gear, final drives, default tire signature).
- `near_duplicate_vehicle_configuration` (advisory): two or more rows share
  the same fuzzy label key (brand + model + variant after stripping case,
  punctuation, and whitespace) but have different math identity. The row
  IDs of the colliding peers are listed in the message.

Both rules go through the existing
`apps/server/vibesensor/data/car_library_validation_allowlist.json`. To
keep an intentional duplicate or label collision, add an entry with the
rule name, the offending row `id`, and a `reason`.

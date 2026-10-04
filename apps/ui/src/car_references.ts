import type { CarRecord } from "./api/types";
import type { components } from "./generated/http_api_contracts";

/**
 * Where a car's order references came from (docs/user_journeys.md §5.1).
 * Shared by the car pages and anything else that explains a car's references.
 */

export type ReferenceProvenance =
  components["schemas"]["ReferenceProvenanceValue"];

/** The provenance chip: how far to trust one value. */
export type ProvenanceTier =
  | "exact"
  | "checked"
  | "estimate"
  | "user"
  | "missing";

export interface CarReferences {
  tire: ReferenceProvenance;
  finalDrive: ReferenceProvenance;
  topGear: ReferenceProvenance;
}

const KNOWN_CONFIDENCES: ReadonlySet<string> = new Set([
  "official_exact",
  "official_derived",
  "reputable_secondary_crosschecked",
  "family_default",
  "unverified",
  "user_confirmed",
]);

/** Library confidences that make a value an estimate (as in the server's source checks). */
export function isWeak(provenance: ReferenceProvenance): boolean {
  return provenance === "family_default" || provenance === "unverified";
}

export function provenanceTier(
  provenance: ReferenceProvenance,
): ProvenanceTier {
  switch (provenance) {
    case "official_exact":
    case "official_derived":
      return "exact";
    case "reputable_secondary_crosschecked":
      return "checked";
    case "user_confirmed":
      return "user";
    case "missing":
      return "missing";
    default:
      return "estimate";
  }
}

/** A recorded confidence, or `fallback` when none (or an unknown one) was recorded. */
export function confidenceProvenance(
  confidence: string | null | undefined,
  fallback: ReferenceProvenance,
): ReferenceProvenance {
  return confidence && KNOWN_CONFIDENCES.has(confidence)
    ? (confidence as ReferenceProvenance)
    : fallback;
}

/**
 * A saved reference's provenance: `missing` without a value, the recorded
 * confidence otherwise. A value saved without one was entered by the user.
 */
function referenceProvenance(
  value: unknown,
  confidence: string | null | undefined,
): ReferenceProvenance {
  if (!(typeof value === "number" && Number.isFinite(value) && value > 0)) {
    return "missing";
  }
  return confidenceProvenance(confidence, "user_confirmed");
}

export function savedCarReferences(car: CarRecord): CarReferences {
  const aspects = car.aspects ?? {};
  const status = car.order_reference_status;
  const tireComplete = [
    aspects.tire_width_mm,
    aspects.tire_aspect_pct,
    aspects.rim_in,
  ].every((value) => typeof value === "number" && value > 0);
  return {
    tire: referenceProvenance(
      tireComplete ? aspects.tire_width_mm : null,
      status?.tire_dimensions_confidence,
    ),
    finalDrive: referenceProvenance(
      aspects.final_drive_ratio,
      status?.final_drive_ratio_confidence,
    ),
    topGear: referenceProvenance(
      aspects.current_gear_ratio,
      status?.current_gear_ratio_confidence,
    ),
  };
}

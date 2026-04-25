import type { CarLibraryGearbox, CarOrderReferenceStatus } from "../../api/types";

type Translate = (key: string, vars?: Record<string, unknown>) => string;

function confidenceLabel(
  confidence: string | null | undefined,
  t: Translate,
): string | null {
  switch (confidence) {
    case "official_exact":
    case "official_derived":
    case "reputable_secondary_crosschecked":
    case "family_default":
    case "unverified":
    case "user_confirmed":
      return t(`settings.car.confidence.${confidence}`);
    default:
      return null;
  }
}

function buildConfidencePart(
  labelKey: string,
  confidence: string | null | undefined,
  t: Translate,
): string | null {
  const label = confidenceLabel(confidence, t);
  if (!label) {
    return null;
  }
  return t(labelKey, { value: label });
}

export function describeOrderReferenceConfidence(
  status: CarOrderReferenceStatus | null | undefined,
  t: Translate,
): string | null {
  if (!status) {
    return null;
  }
  const parts = [
    buildConfidencePart(
      "settings.car.confidence.part_tires",
      status.tire_dimensions_confidence,
      t,
    ),
    buildConfidencePart(
      "settings.car.confidence.part_drive",
      status.final_drive_ratio_confidence,
      t,
    ),
    buildConfidencePart(
      "settings.car.confidence.part_gear",
      status.current_gear_ratio_confidence,
      t,
    ),
    buildConfidencePart(
      "settings.car.confidence.part_transmission",
      status.transmission_confidence,
      t,
    ),
  ].filter((part): part is string => Boolean(part));
  if (parts.length === 0) {
    return null;
  }
  return parts.join(" · ");
}

export function describeGearboxConfidence(
  gearbox: CarLibraryGearbox | null | undefined,
  t: Translate,
): string | null {
  if (!gearbox) {
    return null;
  }
  const parts = [
    buildConfidencePart(
      "settings.car.confidence.part_drive",
      gearbox.final_drive_ratio_confidence,
      t,
    ),
    buildConfidencePart(
      "settings.car.confidence.part_gear",
      gearbox.top_gear_ratio_confidence,
      t,
    ),
    buildConfidencePart(
      "settings.car.confidence.part_transmission",
      gearbox.transmission_confidence,
      t,
    ),
  ].filter((part): part is string => Boolean(part));
  if (parts.length === 0) {
    return null;
  }
  return parts.join(" · ");
}

export function buildOrderReferenceConfidenceDetail(
  status: CarOrderReferenceStatus | null | undefined,
  t: Translate,
): string | null {
  const summary = describeOrderReferenceConfidence(status, t);
  if (!summary) {
    return null;
  }
  if (status?.requires_manual_confirmation) {
    return `${summary}. ${t("settings.car.confidence.review_detail")}`;
  }
  return summary;
}

export function buildGearboxConfidenceHint(
  gearbox: CarLibraryGearbox | null | undefined,
  t: Translate,
): string | null {
  const summary = describeGearboxConfidence(gearbox, t);
  if (!summary) {
    return null;
  }
  if (gearbox?.requires_manual_confirmation) {
    return `${summary}. ${t("settings.car.confidence.review_detail")}`;
  }
  return summary;
}

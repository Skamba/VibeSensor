import { type CarReferences, isWeak } from "./car_references";
import type { components } from "./generated/http_api_contracts";

/**
 * What a run can test per order family (docs/user_journeys.md §5.1), in the
 * server's capture-readiness vocabulary. The dashboard shows the live
 * readiness verdict; the car pages derive the same verdict from a car alone.
 */

export type Capabilities =
  components["schemas"]["RecordingCaptureCapabilitiesResponse"];
export type CapabilityFamily = keyof Capabilities;
/** `ok`: tested; `caveat`: tested, but the result is hedged; `no`: not tested. */
export type CapabilityMark = "ok" | "caveat" | "no";

export const CAPABILITY_FAMILIES: readonly CapabilityFamily[] = [
  "wheel",
  "driveline",
  "engine",
];

const MARKS: Record<string, CapabilityMark> = {
  ok: "ok",
  measured: "ok",
  estimated_final_drive: "caveat",
  estimated_top_gear: "caveat",
  estimated_ratios: "caveat",
};

export const CAPABILITY_MARK_SYMBOL: Record<CapabilityMark, string> = {
  ok: "✓",
  caveat: "~",
  no: "✕",
};

export function capabilityMark(value: string): CapabilityMark {
  return MARKS[value] ?? "no";
}

/** Catalog key of the short reason; `null` for a plain "tested". */
export function capabilityNoteKey(
  family: CapabilityFamily,
  value: string,
): string | null {
  return value === "ok" ? null : `capabilities.${family}.${value}`;
}

/**
 * What a car's references let a run test without OBD-II, as the server's
 * readiness derives it: the wheel needs the tire size, the driveline also the
 * final drive, and the engine estimate also the top gear (it assumes top gear).
 * A missing reference is named: the tire first, then whichever ratio is missing.
 */
export function carCapabilities(refs: CarReferences): Capabilities {
  if (refs.tire === "missing") {
    return {
      wheel: "missing_tire",
      driveline: "missing_tire",
      engine: "missing_tire",
    };
  }
  const hasFinalDrive = refs.finalDrive !== "missing";
  const hasTopGear = refs.topGear !== "missing";
  return {
    wheel: "ok",
    driveline: !hasFinalDrive
      ? "missing_final_drive"
      : isWeak(refs.finalDrive)
        ? "estimated_final_drive"
        : "ok",
    engine:
      !hasFinalDrive && !hasTopGear
        ? "missing_ratios"
        : !hasFinalDrive
          ? "missing_final_drive"
          : !hasTopGear
            ? "missing_top_gear"
            : isWeak(refs.finalDrive) || isWeak(refs.topGear)
              ? "estimated_ratios"
              : "estimated_top_gear",
  };
}

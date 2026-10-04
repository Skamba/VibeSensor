import { defaultLocationCodes } from "./constants";

/**
 * What a set of sensor locations can localise (docs/user_journeys.md §5.2).
 * Shared by the Sensors page and the Live readiness card.
 */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

export type SensorLayoutKind =
  | "single"
  | "no_wheels"
  | "some_wheels"
  | "four_wheels";

const WHEEL_CODES: ReadonlySet<string> = new Set(
  defaultLocationCodes.filter((code) => code.endsWith("_wheel")),
);

export interface SensorLayout {
  kind: SensorLayoutKind;
  wheelCount: number;
}

/** The layout of the sensors that have a location, or `null` when none has. */
export function sensorLayout(
  locationCodes: readonly string[],
): SensorLayout | null {
  const located = locationCodes.filter((code) => code !== "");
  if (located.length === 0) {
    return null;
  }
  const wheelCount = new Set(located.filter((code) => WHEEL_CODES.has(code)))
    .size;
  const kind: SensorLayoutKind =
    located.length === 1
      ? "single"
      : wheelCount === WHEEL_CODES.size
        ? "four_wheels"
        : wheelCount > 0
          ? "some_wheels"
          : "no_wheels";
  return { kind, wheelCount };
}

/** One sentence on what the layout can and cannot tell. */
export function layoutConsequence(layout: SensorLayout, t: Translate): string {
  return t(`sensors.layout.${layout.kind}`, {
    count: layout.wheelCount,
    total: WHEEL_CODES.size,
  });
}

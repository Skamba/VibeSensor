import type { CarRecord } from "./api/types";

/** Pure car-selection derivations shared by the car, analysis, and live pages. */

/** Tire size is the minimum; final drive and top gear are optional references. */
const REQUIRED_CAR_ASPECT_KEYS = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
] as const;

export type RequiredCarAspectKey = (typeof REQUIRED_CAR_ASPECT_KEYS)[number];

export type CarSelectionState =
  | { kind: "loading" }
  | { kind: "no_cars" }
  | { kind: "no_active_car" }
  | { kind: "active"; car: CarRecord };

export interface CarCompleteness {
  isComplete: boolean;
  missingKeys: RequiredCarAspectKey[];
}

export function deriveCarSelection(
  cars: readonly CarRecord[],
  activeCarId: string | null,
  loaded: boolean,
): CarSelectionState {
  if (!loaded) {
    return { kind: "loading" };
  }
  if (!cars.length) {
    return { kind: "no_cars" };
  }
  const car = activeCarId
    ? cars.find((entry) => entry.id === activeCarId)
    : null;
  return car ? { kind: "active", car } : { kind: "no_active_car" };
}

export function getCarCompleteness(car: CarRecord): CarCompleteness {
  const missingKeys = REQUIRED_CAR_ASPECT_KEYS.filter((key) => {
    const value = car.aspects?.[key];
    return !(typeof value === "number" && Number.isFinite(value) && value > 0);
  });
  return { isComplete: missingKeys.length === 0, missingKeys };
}

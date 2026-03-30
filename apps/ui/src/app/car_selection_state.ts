import type { CarRecord } from "../api/types";
import type { SettingsState } from "./ui_app_state";

const REQUIRED_CAR_ASPECT_KEYS = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
  "final_drive_ratio",
  "current_gear_ratio",
] as const;

export type RequiredCarAspectKey = (typeof REQUIRED_CAR_ASPECT_KEYS)[number];

export interface CarSelectionStateSource {
  cars: SettingsState["cars"];
  activeCarId: SettingsState["activeCarId"];
  carsLoaded: SettingsState["carsLoaded"];
}

export type CarSelectionState =
  | { kind: "loading" }
  | { kind: "no_cars" }
  | { kind: "no_active_car" }
  | { kind: "active"; car: CarRecord };

export interface CarCompleteness {
  isComplete: boolean;
  missingKeys: RequiredCarAspectKey[];
}

function isConfiguredAspectValue(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

export function resolveActiveCar(settings: CarSelectionStateSource): CarRecord | null {
  if (!settings.activeCarId) {
    return null;
  }
  return settings.cars.find((car) => car.id === settings.activeCarId) ?? null;
}

export function deriveCarSelectionState(settings: CarSelectionStateSource): CarSelectionState {
  if (!settings.carsLoaded) {
    return { kind: "loading" };
  }
  if (!settings.cars.length) {
    return { kind: "no_cars" };
  }
  const activeCar = resolveActiveCar(settings);
  if (activeCar) {
    return { kind: "active", car: activeCar };
  }
  return { kind: "no_active_car" };
}

export function hasResolvedActiveCar(settings: CarSelectionStateSource): boolean {
  return deriveCarSelectionState(settings).kind === "active";
}

export function getCarCompleteness(car: CarRecord): CarCompleteness {
  const missingKeys = REQUIRED_CAR_ASPECT_KEYS.filter((key) => !isConfiguredAspectValue(car.aspects?.[key]));
  return {
    isComplete: missingKeys.length === 0,
    missingKeys,
  };
}

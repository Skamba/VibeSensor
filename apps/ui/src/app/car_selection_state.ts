import type { CarRecord } from "../api/types";
import type { SettingsState } from "./ui_app_state";

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

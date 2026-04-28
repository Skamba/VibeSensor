import type { CarRecord } from "../api/types";
import type { SettingsState } from "./ui_app_state";
import { computed, type ReadonlySignal } from "./ui_signals";

const REQUIRED_CAR_ASPECT_KEYS = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
  "final_drive_ratio",
  "current_gear_ratio",
] as const;

export type RequiredCarAspectKey = (typeof REQUIRED_CAR_ASPECT_KEYS)[number];

export interface CarSelectionStateSource {
  cars: SettingsState["car"]["cars"];
  activeCarId: SettingsState["car"]["activeCarId"];
  carsLoaded: SettingsState["car"]["carsLoaded"];
}

export type CarSelectionState =
  | { kind: "loading" }
  | { kind: "no_cars" }
  | { kind: "no_active_car" }
  | { kind: "active"; car: CarRecord };

export interface CarSelectionDerivedState {
  activeCar: ReadonlySignal<CarRecord | null>;
  hasResolvedActiveCar: ReadonlySignal<boolean>;
  selection: ReadonlySignal<CarSelectionState>;
}

export interface CarCompleteness {
  isComplete: boolean;
  missingKeys: RequiredCarAspectKey[];
}

function isConfiguredAspectValue(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function resolveActiveCar(settings: CarSelectionStateSource): CarRecord | null {
  if (!settings.activeCarId.value) {
    return null;
  }
  return settings.cars.value.find((car) => car.id === settings.activeCarId.value) ?? null;
}

function deriveCarSelectionState(settings: CarSelectionStateSource): CarSelectionState {
  if (!settings.carsLoaded.value) {
    return { kind: "loading" };
  }
  if (!settings.cars.value.length) {
    return { kind: "no_cars" };
  }
  const activeCar = resolveActiveCar(settings);
  if (activeCar) {
    return { kind: "active", car: activeCar };
  }
  return { kind: "no_active_car" };
}

function hasResolvedActiveCar(settings: CarSelectionStateSource): boolean {
  return deriveCarSelectionState(settings).kind === "active";
}

export function createCarSelectionDerivedState(
  settings: CarSelectionStateSource,
): CarSelectionDerivedState {
  const activeCar = computed(() => resolveActiveCar(settings));
  const selection = computed<CarSelectionState>(() => {
    if (!settings.carsLoaded.value) {
      return { kind: "loading" };
    }
    if (!settings.cars.value.length) {
      return { kind: "no_cars" };
    }
    const resolvedCar = activeCar.value;
    if (resolvedCar) {
      return { kind: "active", car: resolvedCar };
    }
    return { kind: "no_active_car" };
  });
  const hasResolvedActiveCarSignal = computed(
    () => selection.value.kind === "active",
  );

  return {
    activeCar,
    hasResolvedActiveCar: hasResolvedActiveCarSignal,
    selection,
  };
}

export function getCarCompleteness(car: CarRecord): CarCompleteness {
  const missingKeys = REQUIRED_CAR_ASPECT_KEYS.filter((key) => !isConfiguredAspectValue(car.aspects?.[key]));
  return {
    isComplete: missingKeys.length === 0,
    missingKeys,
  };
}

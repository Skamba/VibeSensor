import { computed, effect, signal } from "@preact/signals";

import {
  addSettingsCar,
  deleteSettingsCar,
  setActiveSettingsCar,
} from "../../api/settings";
import type {
  CarOrderReferenceStatus,
  CarUpsertRequest,
} from "../../api/types";
import {
  activeView,
  requestConfirmation,
  settingsTab,
  showError,
} from "../../app_store";
import { getCarCompleteness } from "../../car_selection";
import { t } from "../../i18n";
import { analysisTuning, applyCars, carSettings } from "../../settings_store";

/** The car just created by the wizard, highlighted until the user moves on. */
export const highlighted = signal<{ carId: string; carName: string } | null>(
  null,
);

const carTabVisible = computed(
  () => activeView.value === "settingsView" && settingsTab.value === "carTab",
);

effect(() => {
  if (!carTabVisible.value) {
    highlighted.value = null;
  }
});

let mutationInFlight = false;

/** Runs one car mutation at a time; overlapping requests are ignored. */
async function mutate(run: () => Promise<void>): Promise<boolean> {
  if (mutationInFlight) {
    return false;
  }
  mutationInFlight = true;
  try {
    await run();
    return true;
  } finally {
    mutationInFlight = false;
  }
}

function findCar(carId: string) {
  return carSettings.cars.value.find((car) => car.id === carId) ?? null;
}

/** Creates the car from the wizard and makes it active. Throws on failure. */
export async function createAndActivateCar(car: {
  name: string;
  type: string;
  variant?: string;
  aspects: Record<string, number | string | null>;
  status: CarOrderReferenceStatus;
}): Promise<void> {
  let failureKey = "settings.car.create_failed";
  const started = await mutate(async () => {
    try {
      const request: CarUpsertRequest = {
        // Only the tuning carries over; the new car's references are its own.
        aspects: { ...analysisTuning.value, ...car.aspects },
        name: car.name,
        type: car.type,
        order_reference_status: car.status,
      };
      if (car.variant) {
        request.variant = car.variant;
      }
      const created = await addSettingsCar(request);
      applyCars(created);
      const newCar = created.cars.at(-1);
      if (!newCar) {
        throw new Error("Car creation response did not include a created car.");
      }
      failureKey = "settings.car.activate_failed";
      applyCars(await setActiveSettingsCar(newCar.id));
      highlighted.value = { carId: newCar.id, carName: newCar.name };
    } catch (error) {
      showError(t(failureKey));
      throw error;
    }
  });
  if (!started) {
    throw new Error("A car settings operation is already in progress.");
  }
}

export async function activateCar(carId: string): Promise<void> {
  const car = findCar(carId);
  if (!car) {
    return;
  }
  if (!getCarCompleteness(car).isComplete) {
    showError(t("settings.car.activate_incomplete"));
    return;
  }
  await mutate(async () => {
    try {
      applyCars(await setActiveSettingsCar(carId));
      highlighted.value = null;
    } catch {
      showError(t("settings.car.activate_failed"));
    }
  });
}

/** An incomplete car: make it active, then open the Analysis tab. */
export async function completeCar(carId: string): Promise<void> {
  if (!findCar(carId)) {
    return;
  }
  await mutate(async () => {
    try {
      if (carId !== carSettings.activeCarId.value) {
        applyCars(await setActiveSettingsCar(carId));
      }
      highlighted.value = null;
      settingsTab.value = "analysisTab";
    } catch {
      showError(t("settings.car.activate_failed"));
    }
  });
}

export async function deleteCar(carId: string): Promise<void> {
  const name = findCar(carId)?.name ?? "";
  if (
    !(await requestConfirmation(t("settings.car.delete_confirm", { name })))
  ) {
    return;
  }
  await mutate(async () => {
    try {
      applyCars(await deleteSettingsCar(carId));
      highlighted.value = null;
    } catch {
      showError(t("settings.car.delete_failed"));
    }
  });
}

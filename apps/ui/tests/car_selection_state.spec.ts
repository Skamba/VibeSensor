import { expect, test } from "@playwright/test";

import {
  createCarSelectionDerivedState,
} from "../src/app/car_selection_state";
import { createAppState } from "../src/app/ui_app_state";
import type { CarRecord } from "../src/api/types";

function makeCar(overrides: Partial<CarRecord> = {}): CarRecord {
  return {
    id: "car-1",
    name: "Demo Car",
    type: "Coupe",
    variant: null,
    aspects: {},
    ...overrides,
  };
}

test.describe("car selection derived state", () => {
  test("tracks loading, empty, missing-active, and active states reactively", () => {
    const state = createAppState();
    const derived = createCarSelectionDerivedState(state.settings);

    expect(derived.selection.value).toEqual({ kind: "loading" });
    expect(derived.activeCar.value).toBeNull();
    expect(derived.hasResolvedActiveCar.value).toBe(false);

    state.settings.carsLoaded = true;
    expect(derived.selection.value).toEqual({ kind: "no_cars" });

    state.settings.cars = [makeCar()];
    expect(derived.selection.value).toEqual({ kind: "no_active_car" });

    state.settings.activeCarId = "car-1";
    expect(derived.selection.value).toEqual({
      kind: "active",
      car: makeCar(),
    });
    expect(derived.activeCar.value?.id).toBe("car-1");
    expect(derived.hasResolvedActiveCar.value).toBe(true);

    state.settings.activeCarId = "missing";
    expect(derived.selection.value).toEqual({ kind: "no_active_car" });
    expect(derived.activeCar.value).toBeNull();
    expect(derived.hasResolvedActiveCar.value).toBe(false);
  });
});

import { expect, test } from "@playwright/test";

import {
  createCarsManualInputStore,
  type CarsFeatureManualInputState,
} from "../src/app/features/cars_manual_input";
import { effect, signal } from "../src/app/ui_signals";

function formatManualInputs(inputs: CarsFeatureManualInputState): string {
  return [
    inputs.finalDrive,
    inputs.rim,
    inputs.tireAspect,
    inputs.tireWidth,
    inputs.topGear,
  ].join(":");
}

test.describe("createCarsManualInputStore", () => {
  test("batches multi-field writes into one reactive invalidation", () => {
    const step = signal(4);
    const store = createCarsManualInputStore(step);
    const seenSnapshots: string[] = [];

    const dispose = effect(() => {
      seenSnapshots.push(formatManualInputs(store.state.value));
    });

    expect(seenSnapshots).toEqual(["3.08:18:45:225:0.64"]);

    store.write({
      finalDrive: "4.10",
      rim: "20",
      tireAspect: "40",
      tireWidth: "285",
      topGear: "0.71",
    });

    expect(seenSnapshots).toEqual([
      "3.08:18:45:225:0.64",
      "4.10:20:40:285:0.71",
    ]);

    dispose();
  });
});

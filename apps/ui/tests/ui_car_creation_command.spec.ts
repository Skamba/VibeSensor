import { expect, test } from "@playwright/test";

import { createUiCarCreationCommand } from "../src/app/runtime/ui_car_creation_command";
import type { CarUpsertRequest, CarsPayload } from "../src/api/types";
import { defaultVehicleSettings } from "../src/app/ui_app_state";

test.describe("createUiCarCreationCommand", () => {
  test("creates a car through the narrow runtime seam and preserves the activate-and-sync flow", async () => {
    const payloadCalls: CarsPayload[] = [];
    const lifecycleCalls: string[] = [];
    const addRequests: CarUpsertRequest[] = [];
    const setActiveRequests: string[] = [];
    const createdCarsPayload: CarsPayload = {
      cars: [
        {
          id: "car-1",
          name: "Existing",
          type: "Hatchback",
          variant: "Stock",
          aspects: { tire_width_mm: 205 },
        },
        {
          id: "car-2",
          name: "Volvo XC40 Recharge",
          type: "SUV",
          variant: "Twin Motor",
          aspects: { tire_width_mm: 235, final_drive_ratio: 9.1 },
        },
      ],
      active_car_id: "car-1",
    };
    const activatedCarsPayload: CarsPayload = {
      ...createdCarsPayload,
      active_car_id: "car-2",
    };
    const command = createUiCarCreationCommand({
      getVehicleSettings: () => ({
        ...defaultVehicleSettings,
        tire_width_mm: 205,
        tire_aspect_pct: 55,
        rim_in: 16,
        final_drive_ratio: 3.9,
        current_gear_ratio: 0.82,
      }),
      syncCarsPayload: (payload) => {
        payloadCalls.push(payload);
        lifecycleCalls.push(`syncCarsPayload:${payload.active_car_id ?? "none"}`);
      },
      syncActiveCarToInputs: () => {
        lifecycleCalls.push("syncActiveCarToInputs");
      },
      showCarCreationSuccess: (carId, carName) => {
        lifecycleCalls.push(`showCarCreationSuccess:${carId}:${carName}`);
      },
      renderCarList: () => {
        lifecycleCalls.push("renderCarList");
      },
      refreshSpectrumDecorations: () => {
        lifecycleCalls.push("refreshSpectrumDecorations");
      },
      addSettingsCar: async (payload) => {
        addRequests.push(payload);
        return createdCarsPayload;
      },
      setActiveSettingsCar: async (carId) => {
        setActiveRequests.push(carId);
        return activatedCarsPayload;
      },
    });

    await command.addCarFromWizard(
      "Volvo XC40 Recharge",
      "SUV",
      {
        tire_width_mm: 235,
        tire_aspect_pct: 45,
        rim_in: 19,
        final_drive_ratio: 9.1,
        current_gear_ratio: 0.71,
      },
      "Twin Motor",
    );

    expect(addRequests).toEqual([
      {
        name: "Volvo XC40 Recharge",
        type: "SUV",
        variant: "Twin Motor",
        aspects: {
          ...defaultVehicleSettings,
          tire_width_mm: 235,
          tire_aspect_pct: 45,
          rim_in: 19,
          final_drive_ratio: 9.1,
          current_gear_ratio: 0.71,
        },
      },
      ]);
    expect(setActiveRequests).toEqual(["car-2"]);
    expect(payloadCalls).toEqual([createdCarsPayload, activatedCarsPayload]);
    expect(lifecycleCalls).toEqual([
      "syncCarsPayload:car-1",
      "syncCarsPayload:car-2",
      "syncActiveCarToInputs",
      "showCarCreationSuccess:car-2:Volvo XC40 Recharge",
      "renderCarList",
      "refreshSpectrumDecorations",
    ]);
  });

  test("preserves the current silent failure behavior when creation fails", async () => {
    const lifecycleCalls: string[] = [];
    const command = createUiCarCreationCommand({
      getVehicleSettings: () => ({
        ...defaultVehicleSettings,
        tire_width_mm: 205,
      }),
      syncCarsPayload: () => {
        lifecycleCalls.push("syncCarsPayload");
      },
      syncActiveCarToInputs: () => {
        lifecycleCalls.push("syncActiveCarToInputs");
      },
      renderCarList: () => {
        lifecycleCalls.push("renderCarList");
      },
      refreshSpectrumDecorations: () => {
        lifecycleCalls.push("refreshSpectrumDecorations");
      },
      addSettingsCar: async () => {
        throw new Error("network failed");
      },
    });

    await command.addCarFromWizard("My Car", "Custom", { tire_width_mm: 225 });

    expect(lifecycleCalls).toEqual([]);
  });
});

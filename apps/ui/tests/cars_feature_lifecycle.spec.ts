import { beforeEach, describe, expect, test, vi } from "vitest";
import type { CarLibraryModel, CarsPayload } from "../src/api/types";
import { serverStateQueryKeys } from "../src/app/features/server_state_query_keys";
import { createDeferred, flushAsyncWork } from "./async_test_helpers";
import {
  createCarsHarness,
  EXAMPLE_MANUAL_INPUTS,
  makeCarsPayload,
  makeModel,
} from "./cars_feature_test_support";

const api = vi.hoisted(() => ({
  addSettingsCar: vi.fn(),
  deleteSettingsCar: vi.fn(),
  getCarLibraryBrands: vi.fn(),
  getCarLibraryModels: vi.fn(),
  getCarLibraryTypes: vi.fn(),
  setActiveSettingsCar: vi.fn(),
}));

vi.mock("../src/api/car_library", () => ({
  getCarLibraryBrands: api.getCarLibraryBrands,
  getCarLibraryModels: api.getCarLibraryModels,
  getCarLibraryTypes: api.getCarLibraryTypes,
}));

vi.mock("../src/api/settings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/settings")>()),
  addSettingsCar: api.addSettingsCar,
  deleteSettingsCar: api.deleteSettingsCar,
  setActiveSettingsCar: api.setActiveSettingsCar,
}));

beforeEach(() => {
  vi.resetAllMocks();
});

describe("cars feature wizard async lifecycle", () => {
  test("ignores brand load results after the wizard closes", async () => {
    const brands = createDeferred<string[]>();
    api.getCarLibraryBrands.mockImplementation(async () => ({
      brands: await brands.promise,
    }));
    const harness = createCarsHarness();

    const opening = harness.feature.openWizard();
    await flushAsyncWork();
    await harness.feature.handleWizardAction({ type: "close" });
    brands.resolve(["BMW"]);
    await opening;

    expect(harness.renderState().isOpen).toBe(false);
    expect(harness.renderState().brandOptions.status).toBe("loading");
    expect(harness.focuses).toEqual(["close"]);
  });

  test("ignores stale type results after navigating back", async () => {
    const types = createDeferred<string[]>();
    api.getCarLibraryBrands.mockResolvedValue({ brands: ["BMW"] });
    api.getCarLibraryTypes.mockImplementation(async () => ({
      types: await types.promise,
    }));
    const harness = createCarsHarness();

    await harness.feature.openWizard();
    const selectingBrand = harness.feature.handleWizardAction({
      type: "select-brand",
      value: "BMW",
    });
    await flushAsyncWork();
    await harness.feature.handleWizardAction({ type: "back" });
    types.resolve(["SUV"]);
    await selectingBrand;

    expect(harness.renderState().step).toBe(0);
    expect(harness.renderState().typeOptions.status).toBe("loading");
    expect(harness.focuses).not.toContain("type-option");
  });

  test("keeps newer model options when an older model load resolves later", async () => {
    const suvModels = createDeferred<CarLibraryModel[]>();
    const sedanModels = createDeferred<CarLibraryModel[]>();
    api.getCarLibraryBrands.mockResolvedValue({ brands: ["BMW"] });
    api.getCarLibraryTypes.mockResolvedValue({ types: ["SUV", "Sedan"] });
    api.getCarLibraryModels.mockImplementation(
      async (_brand: string, carType: string) => ({
        models: await (carType === "SUV"
          ? suvModels.promise
          : sedanModels.promise),
      }),
    );
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "BMW" });
    const selectingSuv = feature.handleWizardAction({
      type: "select-type",
      value: "SUV",
    });
    await flushAsyncWork();
    const selectingSedan = feature.handleWizardAction({
      type: "select-type",
      value: "Sedan",
    });
    await flushAsyncWork();
    sedanModels.resolve([makeModel({ model: "M3", type: "Sedan" })]);
    await selectingSedan;
    suvModels.resolve([makeModel({ model: "X5", type: "SUV" })]);
    await selectingSuv;

    expect(harness.renderState().modelOptions).toMatchObject({
      status: "ready",
      options: [expect.objectContaining({ model: "M3" })],
    });
    expect(harness.renderState().step).toBe(2);
  });
});

describe("cars feature saved-car mutations", () => {
  test("keeps the wizard open and reports activation failures after create", async () => {
    const createdPayload = makeCarsPayload("car-1");
    api.getCarLibraryBrands.mockResolvedValue({ brands: [] });
    api.addSettingsCar.mockResolvedValue(createdPayload);
    api.setActiveSettingsCar.mockRejectedValue(new Error("activation failed"));
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({
      type: "submit-custom-brand",
      value: "Track",
    });
    await feature.handleWizardAction({
      type: "submit-custom-type",
      value: "Coupe",
    });
    await feature.handleWizardAction({
      type: "submit-custom-model",
      value: "Car",
    });
    harness.updateManualInputs(EXAMPLE_MANUAL_INPUTS);
    await feature.handleWizardAction({ type: "finish" });

    expect(harness.errors).toEqual(["settings.car.activate_failed"]);
    expect(
      harness.queryClient.getQueryData(serverStateQueryKeys.settings.cars()),
    ).toEqual(createdPayload);
    expect(harness.appState.settings.car.activeCarId.value).toBe("car-1");
    expect(harness.lifecycleCalls).toEqual([]);
    expect(harness.renderState().isOpen).toBe(true);
    expect(harness.focuses.at(-1)).toBe("finish");
  });

  test("ignores activate results after disposal", async () => {
    const activate = createDeferred<CarsPayload>();
    api.setActiveSettingsCar.mockReturnValue(activate.promise);
    const harness = createCarsHarness();
    harness.feature.bindHandlers();
    harness.seedCars(makeCarsPayload("car-1"));

    harness.listAction({ type: "activate", carId: "car-2" });
    await flushAsyncWork();
    harness.feature.dispose();
    activate.resolve(makeCarsPayload("car-2"));
    await flushAsyncWork();

    expect(harness.appState.settings.car.activeCarId.value).toBe("car-1");
    expect(harness.lifecycleCalls).toEqual([]);
    expect(harness.errors).toEqual([]);
  });

  test("ignores overlapping car mutations while one is in flight", async () => {
    const activate = createDeferred<CarsPayload>();
    api.setActiveSettingsCar.mockReturnValue(activate.promise);
    const harness = createCarsHarness();
    harness.feature.bindHandlers();
    harness.seedCars(makeCarsPayload("car-1"));

    harness.listAction({ type: "activate", carId: "car-2" });
    harness.listAction({ type: "activate", carId: "car-1" });
    await flushAsyncWork();
    activate.resolve(makeCarsPayload("car-2"));
    await flushAsyncWork();

    expect(api.setActiveSettingsCar.mock.calls).toEqual([["car-2"]]);
    expect(harness.appState.settings.car.activeCarId.value).toBe("car-2");
    expect(harness.lifecycleCalls).toEqual(["refreshSpectrumDecorations"]);
    expect(harness.errors).toEqual([]);
  });

  test("deletes a saved car after confirmation", async () => {
    const remaining: CarsPayload = {
      active_car_id: "car-1",
      cars: makeCarsPayload("car-1").cars.slice(0, 1),
    };
    api.deleteSettingsCar.mockResolvedValue(remaining);
    const confirmations: boolean[] = [];
    const harness = createCarsHarness({
      requestConfirmation: async () => {
        confirmations.push(true);
        return true;
      },
    });
    harness.feature.bindHandlers();
    harness.seedCars(makeCarsPayload("car-1"));

    harness.listAction({ type: "delete", carId: "car-2" });
    await flushAsyncWork();

    expect(confirmations).toEqual([true]);
    expect(api.deleteSettingsCar).toHaveBeenCalledWith("car-2");
    expect(harness.appState.settings.car.cars.value).toEqual(remaining.cars);
    expect(harness.lifecycleCalls).toEqual(["refreshSpectrumDecorations"]);
  });
});

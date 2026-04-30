import { expect, test } from "vitest";
import { createSettingsCarsModule } from "../src/app/features/settings_cars_module";
import { serverStateQueryKeys } from "../src/app/features/server_state_query_keys";
import { signal } from "../src/app/ui_signals";
import { createAppState } from "../src/app/ui_app_state";
import type { CarsListPanelView } from "../src/app/views/cars_panel";
import type { CarsPayload } from "../src/api/types";
import { createDeferred, flushAsyncWork } from "./async_test_helpers";
import { createTestQueryClient } from "./query_client_test_support";

function makePayload(activeCarId: string): CarsPayload {
  return {
    active_car_id: activeCarId,
    cars: [
      {
        id: "car-1",
        name: "Existing",
        type: "Hatchback",
        variant: null,
        aspects: {
          current_gear_ratio: 0.82,
          final_drive_ratio: 3.9,
          rim_in: 16,
          tire_aspect_pct: 55,
          tire_width_mm: 205,
        },
      },
      {
        id: "car-2",
        name: "Track",
        type: "Coupe",
        variant: null,
        aspects: {
          current_gear_ratio: 0.72,
          final_drive_ratio: 3.23,
          rim_in: 19,
          tire_aspect_pct: 40,
          tire_width_mm: 245,
        },
      },
    ],
  };
}

function createModuleHarness(
  overrides: {
    transport?: Parameters<typeof createSettingsCarsModule>[0]["transport"];
    requestConfirmation?: () => Promise<boolean>;
  } = {},
) {
  const appState = createAppState();
  const queryClient = createTestQueryClient();
  const errors: string[] = [];
  const lifecycleCalls: string[] = [];
  const panel: CarsListPanelView = {
    actions: signal(null),
    model: signal(null),
  };
  const module = createSettingsCarsModule({
    queryClient,
    settings: appState.settings,
    panels: {
      analysisPanel: {
        carAvailability: signal(null),
      },
      panel,
    },
    ports: {
      activeViewId: signal("settingsView"),
      activeSettingsTabId: signal("carTab"),
      openAnalysisTab: () => {
        lifecycleCalls.push("openAnalysisTab");
      },
      openCarWizard: () => undefined,
      refreshSpectrumDecorations: () => {
        lifecycleCalls.push("refreshSpectrumDecorations");
      },
      syncAnalysisInputs: () => {
        lifecycleCalls.push("syncAnalysisInputs");
      },
    },
    services: {
      t: (key) => key,
      requestConfirmation: overrides.requestConfirmation ?? (async () => true),
      showError: (message) => {
        errors.push(message);
      },
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
    transport: overrides.transport,
  });
  return { appState, errors, lifecycleCalls, module, panel, queryClient };
}

test("settings cars module keeps wizard open failure observable when activation after create fails", async () => {
  const createdPayload = makePayload("car-1");
  const harness = createModuleHarness({
    transport: {
      async activateCar() {
        throw new Error("activation failed");
      },
      async createCar() {
        return createdPayload;
      },
    },
  });

  await expect(
    harness.module.addCarFromWizard("Track", "Coupe", {
      tire_width_mm: 245,
    }),
  ).rejects.toThrow("activation failed");

  expect(harness.errors).toEqual(["settings.car.activate_failed"]);
  expect(
    harness.queryClient.getQueryData(serverStateQueryKeys.settings.cars()),
  ).toEqual(createdPayload);
  expect(harness.appState.settings.car.activeCarId.value).toBe("car-1");
  expect(harness.lifecycleCalls).toEqual([]);
});

test("settings cars module ignores load results after disposal", async () => {
  const load = createDeferred<CarsPayload>();
  const harness = createModuleHarness({
    transport: {
      async loadCars() {
        return load.promise;
      },
    },
  });

  const loading = harness.module.loadCarsFromServer();
  await flushAsyncWork();
  harness.module.dispose();
  load.resolve(makePayload("car-2"));
  await loading;

  expect(harness.appState.settings.car.activeCarId.value).toBeNull();
  expect(harness.lifecycleCalls).toEqual([]);
  expect(harness.errors).toEqual([]);
});

test("settings cars module ignores activate results after disposal", async () => {
  const activate = createDeferred<CarsPayload>();
  const harness = createModuleHarness({
    transport: {
      async activateCar() {
        return activate.promise;
      },
    },
  });
  harness.module.bindHandlers();
  harness.module.syncCarsPayload(makePayload("car-1"));

  harness.panel.actions.value?.onAction({ type: "activate", carId: "car-2" });
  await flushAsyncWork();
  harness.module.dispose();
  activate.resolve(makePayload("car-2"));
  await flushAsyncWork();

  expect(harness.appState.settings.car.activeCarId.value).toBe("car-1");
  expect(harness.lifecycleCalls).toEqual([]);
  expect(harness.errors).toEqual([]);
});

test("settings cars module ignores overlapping car mutations while one is in flight", async () => {
  const activate = createDeferred<CarsPayload>();
  const activateRequests: string[] = [];
  const harness = createModuleHarness({
    transport: {
      async activateCar(carId) {
        activateRequests.push(carId);
        return activate.promise;
      },
    },
  });
  harness.module.bindHandlers();
  harness.module.syncCarsPayload(makePayload("car-1"));

  harness.panel.actions.value?.onAction({ type: "activate", carId: "car-2" });
  harness.panel.actions.value?.onAction({ type: "activate", carId: "car-1" });
  await flushAsyncWork();
  activate.resolve(makePayload("car-2"));
  await flushAsyncWork();

  expect(activateRequests).toEqual(["car-2"]);
  expect(harness.appState.settings.car.activeCarId.value).toBe("car-2");
  expect(harness.lifecycleCalls).toEqual([
    "syncAnalysisInputs",
    "refreshSpectrumDecorations",
  ]);
  expect(harness.errors).toEqual([]);
});

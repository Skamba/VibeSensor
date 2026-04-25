import { expect, test } from "vitest";
import { createSettingsCarsModule } from "../src/app/features/settings_cars_module";
import { serverStateQueryKeys } from "../src/app/features/server_state_query_keys";
import { effect, signal } from "../src/app/ui_signals";
import type {
  CarsListRenderModel,
  CarsListPanelView,
} from "../src/app/views/cars_panel";
import { createAppState } from "../src/app/ui_app_state";
import type { CarsPayload } from "../src/api/types";
import { createTestQueryClient } from "./query_client_test_support";

function lastRender(renders: CarsListRenderModel[]): CarsListRenderModel {
  const render = renders.at(-1);
  if (!render) {
    throw new Error("Expected cars panel to render");
  }
  return render;
}

test("settings cars module dismisses transient creation feedback through typed tab and view callbacks", () => {
  const state = createAppState().settings;
  const renders: CarsListRenderModel[] = [];
  const activeViewId = signal("settingsView");
  const activeSettingsTabId = signal("carTab");

  const panel: CarsListPanelView = {
    actions: signal(null),
    model: signal(null),
  };
  effect(() => {
    const model = panel.model.value;
    if (model === null) {
      return;
    }
    renders.push(model.value);
  });

  const module = createSettingsCarsModule({
    queryClient: createTestQueryClient(),
    settings: state,
    panels: {
      analysisPanel: {
        carAvailability: signal(null),
      },
      panel,
    },
    ports: {
      activeViewId,
      activeSettingsTabId,
      openAnalysisTab: () => undefined,
      openCarWizard: () => undefined,
      refreshSpectrumDecorations: () => undefined,
      syncAnalysisInputs: () => undefined,
    },
    services: {
      t: (key, vars) => {
        if (key === "settings.car.created_body") {
          return `${vars?.name ?? "Unknown"} was added and selected for this setup.`;
        }
        return key;
      },
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
  });

  const payload: CarsPayload = {
    active_car_id: "car-1",
    cars: [
      {
        id: "car-1",
        name: "Track Demo",
        type: "Coupe",
        variant: null,
        aspects: {
          tire_width_mm: 225,
          tire_aspect_pct: 45,
          rim_in: 18,
          final_drive_ratio: 3.08,
          current_gear_ratio: 0.64,
        },
      },
    ],
  };

  module.bindHandlers();
  module.syncCarsPayload(payload);
  module.showCarCreationSuccess("car-1", "Track Demo");

  const highlighted = lastRender(renders);
  expect(highlighted.guidance).toMatchObject({
    titleText: "settings.car.created_title",
    tone: "success",
  });
  expect(highlighted.table?.kind).toBe("rows");
  if (highlighted.table?.kind !== "rows") {
    return;
  }
  expect(highlighted.table.rows[0].isHighlighted).toBe(true);
  expect(highlighted.table.rows[0].highlightedStatusText).toBe(
    "settings.car.just_added",
  );

  activeSettingsTabId.value = "analysisTab";

  const dismissedByTab = lastRender(renders);
  expect(dismissedByTab.guidance).toBeNull();
  expect(dismissedByTab.table?.kind).toBe("rows");
  if (dismissedByTab.table?.kind !== "rows") {
    return;
  }
  expect(dismissedByTab.table.rows[0].isHighlighted).toBe(false);
  expect(dismissedByTab.table.rows[0].highlightedStatusText).toBeNull();

  module.showCarCreationSuccess("car-1", "Track Demo");
  activeViewId.value = "dashboardView";

  const dismissedByView = lastRender(renders);
  expect(dismissedByView.guidance).toBeNull();
  expect(dismissedByView.table?.kind).toBe("rows");
  if (dismissedByView.table?.kind !== "rows") {
    return;
  }
  expect(dismissedByView.table.rows[0].isHighlighted).toBe(false);
  expect(dismissedByView.table.rows[0].highlightedStatusText).toBeNull();
});

test("settings cars module loads cars through the shared async loader without overwriting analysis-owned settings", async () => {
  const state = createAppState().settings;
  const renders: CarsListRenderModel[] = [];
  let syncAnalysisInputsCalls = 0;

  state.analysis.vehicleSettings.value = {
    ...state.analysis.vehicleSettings.value,
    wheel_bandwidth_pct: 7.5,
    speed_uncertainty_pct: 2.5,
    min_abs_band_hz: 1.5,
  };

  const panel: CarsListPanelView = {
    actions: signal(null),
    model: signal(null),
  };
  effect(() => {
    const model = panel.model.value;
    if (model === null) {
      return;
    }
    renders.push(model.value);
  });

  const module = createSettingsCarsModule({
    queryClient: createTestQueryClient(),
    settings: state,
    panels: {
      analysisPanel: {
        carAvailability: signal(null),
      },
      panel,
    },
    ports: {
      activeViewId: signal("settingsView"),
      activeSettingsTabId: signal("carTab"),
      openAnalysisTab: () => undefined,
      openCarWizard: () => undefined,
      refreshSpectrumDecorations: () => undefined,
      syncAnalysisInputs: () => {
        syncAnalysisInputsCalls += 1;
      },
    },
    services: {
      t: (key) => key,
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
    transport: {
      async loadCars() {
        return {
          active_car_id: "car-1",
          cars: [
            {
              id: "car-1",
              name: "Track Demo",
              type: "Coupe",
              variant: null,
              aspects: {
                tire_width_mm: 245,
                tire_aspect_pct: 40,
                rim_in: 19,
                final_drive_ratio: 3.23,
                current_gear_ratio: 0.72,
                wheel_bandwidth_pct: 99,
                speed_uncertainty_pct: 99,
                min_abs_band_hz: 99,
              },
            },
          ],
        };
      },
    },
  });

  await module.loadCarsFromServer();

  expect(state.car.activeCarId.value).toBe("car-1");
  expect(state.car.activeVehicleSettings.value).toMatchObject({
    current_gear_ratio: 0.72,
    final_drive_ratio: 3.23,
    rim_in: 19,
    tire_aspect_pct: 40,
    tire_width_mm: 245,
  });
  expect(state.analysis.vehicleSettings.value).toMatchObject({
    min_abs_band_hz: 1.5,
    speed_uncertainty_pct: 2.5,
    wheel_bandwidth_pct: 7.5,
  });
  expect(syncAnalysisInputsCalls).toBe(1);
  expect(lastRender(renders).table?.kind).toBe("rows");
});

test("settings cars module creates and activates wizard cars through the shared query cache", async () => {
  const appState = createAppState();
  const queryClient = createTestQueryClient();
  const lifecycleCalls: string[] = [];
  const createRequests: Array<Record<string, unknown>> = [];
  const activateRequests: string[] = [];
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

  appState.settings.car.activeVehicleSettings.value = {
    ...appState.settings.car.activeVehicleSettings.value,
    tire_width_mm: 205,
    tire_aspect_pct: 55,
    rim_in: 16,
    final_drive_ratio: 3.9,
    current_gear_ratio: 0.82,
  };

  const module = createSettingsCarsModule({
    queryClient,
    settings: appState.settings,
    panels: {
      analysisPanel: {
        carAvailability: signal(null),
      },
      panel: {
        actions: signal(null),
        model: signal(null),
      },
    },
    ports: {
      activeViewId: signal("settingsView"),
      activeSettingsTabId: signal("carTab"),
      openAnalysisTab: () => undefined,
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
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
    transport: {
      async activateCar(carId) {
        activateRequests.push(carId);
        return activatedCarsPayload;
      },
      async createCar(payload) {
        createRequests.push(payload as Record<string, unknown>);
        return createdCarsPayload;
      },
      async deleteCar() {
        throw new Error("not used");
      },
      async loadCars() {
        throw new Error("not used");
      },
    },
  });

  await module.addCarFromWizard(
    "Volvo XC40 Recharge",
    "SUV",
    {
      tire_width_mm: 235,
      tire_aspect_pct: 45,
      rim_in: 19,
      final_drive_ratio: 9.1,
      current_gear_ratio: 0.71,
    },
    {
      selection_source_status: "compat_projection",
      final_drive_ratio_confidence: "family_default",
      current_gear_ratio_confidence: "family_default",
      transmission_name: "Single-speed fixed gear",
      transmission_confidence: "family_default",
      requires_manual_confirmation: true,
    },
    "Twin Motor",
  );

  expect(createRequests).toEqual([
    {
      aspects: expect.objectContaining({
        current_gear_ratio: 0.71,
        final_drive_ratio: 9.1,
        rim_in: 19,
        tire_aspect_pct: 45,
        tire_width_mm: 235,
      }),
      name: "Volvo XC40 Recharge",
      order_reference_status: {
        current_gear_ratio_confidence: "family_default",
        final_drive_ratio_confidence: "family_default",
        requires_manual_confirmation: true,
        selection_source_status: "compat_projection",
        transmission_confidence: "family_default",
        transmission_name: "Single-speed fixed gear",
      },
      type: "SUV",
      variant: "Twin Motor",
    },
  ]);
  expect(activateRequests).toEqual(["car-2"]);
  expect(
    queryClient.getQueryData(serverStateQueryKeys.settings.cars()),
  ).toEqual(activatedCarsPayload);
  expect(appState.settings.car.activeCarId.value).toBe("car-2");
  expect(lifecycleCalls).toEqual([
    "syncAnalysisInputs",
    "refreshSpectrumDecorations",
  ]);
});

test("settings cars module preserves current silent wizard failure behavior", async () => {
  const lifecycleCalls: string[] = [];
  const module = createSettingsCarsModule({
    queryClient: createTestQueryClient(),
    settings: createAppState().settings,
    panels: {
      analysisPanel: {
        carAvailability: signal(null),
      },
      panel: {
        actions: signal(null),
        model: signal(null),
      },
    },
    ports: {
      activeViewId: signal("settingsView"),
      activeSettingsTabId: signal("carTab"),
      openAnalysisTab: () => undefined,
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
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
    transport: {
      async activateCar() {
        throw new Error("not used");
      },
      async createCar() {
        throw new Error("network failed");
      },
      async deleteCar() {
        throw new Error("not used");
      },
      async loadCars() {
        throw new Error("not used");
      },
    },
  });

  await module.addCarFromWizard("My Car", "Custom", { tire_width_mm: 225 });

  expect(lifecycleCalls).toEqual([]);
});

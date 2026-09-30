import { vi } from "vitest";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarsPayload,
  CarUpsertRequest,
} from "../src/api/types";
import {
  createCarsFeature,
  type CarsFeatureFocusTarget,
} from "../src/app/features/cars_feature";
import type { CarsFeatureManualInputState } from "../src/app/features/cars_wizard_state";
import { applyCarsPayloadToSettings } from "../src/app/features/dashboard_startup_state";
import { createAppState } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import type {
  CarsListRenderModel,
  CarsPanelView,
} from "../src/app/views/cars_panel";
import { createTestQueryClient } from "./query_client_test_support";

/**
 * The cars feature calls the `api/*` wrappers directly; specs replace them with
 * these mocks via `vi.mock("../src/api/settings")` /
 * `vi.mock("../src/api/car_library")` (see `mockCarsApiModules`).
 */
export type CarsApiMocks = {
  addSettingsCar: ReturnType<typeof vi.fn>;
  deleteSettingsCar: ReturnType<typeof vi.fn>;
  getCarLibraryBrands: ReturnType<typeof vi.fn>;
  getCarLibraryModels: ReturnType<typeof vi.fn>;
  getCarLibraryTypes: ReturnType<typeof vi.fn>;
  setActiveSettingsCar: ReturnType<typeof vi.fn>;
};

function createTranslator(): (
  key: string,
  vars?: Record<string, unknown>,
) => string {
  return (key, vars) => {
    if (key === "settings.car.created_body") {
      return `${vars?.name ?? "Unknown"} was added and selected for this setup.`;
    }
    if (vars?.current && vars?.total && vars?.step) {
      return `${key}:${vars.current}/${vars.total}:${String(vars.step)}`;
    }
    return key;
  };
}

export function createCarsHarness(
  overrides: {
    activeSettingsTabId?: string;
    activeViewId?: string;
    requestConfirmation?: () => Promise<boolean>;
  } = {},
) {
  const appState = createAppState();
  const queryClient = createTestQueryClient();
  const errors: string[] = [];
  const focuses: CarsFeatureFocusTarget[] = [];
  const lifecycleCalls: string[] = [];
  const listRenders: CarsListRenderModel[] = [];
  const activeViewId = signal(overrides.activeViewId ?? "settingsView");
  const activeSettingsTabId = signal(overrides.activeSettingsTabId ?? "carTab");
  const panel: CarsPanelView = {
    list: { actions: signal(null), model: signal(null) },
    wizard: {
      actions: signal(null),
      focus(target): void {
        focuses.push(target);
      },
      model: signal(null),
    },
  };
  effect(() => {
    const model = panel.list.model.value;
    if (model !== null) {
      listRenders.push(model.value);
    }
  });
  const feature = createCarsFeature({
    settings: appState.settings,
    queryClient,
    panel,
    analysisPanel: { carAvailability: signal(null) },
    activeViewId,
    activeSettingsTabId,
    openAnalysisTab: () => {
      lifecycleCalls.push("openAnalysisTab");
    },
    refreshSpectrumDecorations: () => {
      lifecycleCalls.push("refreshSpectrumDecorations");
    },
    syncAnalysisInputs: () => {
      lifecycleCalls.push("syncAnalysisInputs");
    },
    services: {
      t: createTranslator(),
      requestConfirmation: overrides.requestConfirmation ?? (async () => true),
      showError: (message) => {
        errors.push(message);
      },
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
  });
  return {
    activeSettingsTabId,
    activeViewId,
    appState,
    errors,
    feature,
    focuses,
    lifecycleCalls,
    listAction(action: {
      type: "activate" | "complete" | "delete" | "add";
      carId: string | null;
    }): void {
      panel.list.actions.value?.onAction(action);
    },
    lastListRender(): CarsListRenderModel {
      const render = listRenders.at(-1);
      if (!render) {
        throw new Error("Expected cars panel to render");
      }
      return render;
    },
    panel,
    queryClient,
    renderState() {
      return feature.wizardRenderState.value;
    },
    /** Seeds saved cars the way the dashboard startup load does. */
    seedCars(payload: CarsPayload): void {
      applyCarsPayloadToSettings(appState.settings.car, payload);
    },
    updateManualInputs(updates: Partial<CarsFeatureManualInputState>): void {
      for (const [field, value] of Object.entries(updates) as Array<
        [keyof CarsFeatureManualInputState, string]
      >) {
        void feature.handleWizardAction({
          type: "manual-input-changed",
          field,
          value,
        });
      }
    },
  };
}

/**
 * Makes `addSettingsCar` append the requested car and `setActiveSettingsCar`
 * activate it, mirroring the server's create-then-activate responses.
 */
export function acceptCarCreation(
  api: CarsApiMocks,
  existing: CarsPayload = { active_car_id: null, cars: [] },
): CarUpsertRequest[] {
  const requests: CarUpsertRequest[] = [];
  let latest = existing;
  api.addSettingsCar.mockImplementation(async (payload: CarUpsertRequest) => {
    requests.push(payload);
    latest = {
      ...latest,
      cars: [
        ...latest.cars,
        {
          id: `car-${latest.cars.length + 1}`,
          name: payload.name ?? "",
          type: payload.type ?? "",
          variant: payload.variant ?? null,
          aspects: payload.aspects ?? {},
        },
      ],
    };
    return latest;
  });
  api.setActiveSettingsCar.mockImplementation(async (carId: string) => {
    latest = { ...latest, active_car_id: carId };
    return latest;
  });
  return requests;
}

export function makeGearbox(
  overrides: Partial<CarLibraryGearbox> = {},
): CarLibraryGearbox {
  return {
    final_drive_ratio: 3.15,
    name: "8-speed automatic",
    final_drive_ratio_confidence: "official_exact",
    requires_manual_confirmation: false,
    source_status: "exact_row",
    top_gear_ratio: 0.67,
    top_gear_ratio_confidence: "official_exact",
    transmission_confidence: "official_exact",
    ...overrides,
  };
}

export function makeTireOption(
  overrides: Partial<CarLibraryTireOption> = {},
): CarLibraryTireOption {
  return {
    default_axle_for_speed: "rear",
    front: {
      width_mm: 275,
      aspect_pct: 40,
      rim_in: 21,
    },
    name: "Factory staggered",
    rear: null,
    rim_in: 21,
    source_confidence: "official_exact",
    tire_aspect_pct: 40,
    tire_width_mm: 275,
    ...overrides,
  };
}

export function makeModel(
  overrides: Partial<CarLibraryModel> = {},
): CarLibraryModel {
  return {
    brand: "BMW",
    gearboxes: [],
    model: "X5",
    rim_in: 21,
    tire_aspect_pct: 40,
    tire_options: [],
    tire_width_mm: 275,
    type: "SUV",
    variants: [],
    ...overrides,
  };
}

export function makeCarsPayload(activeCarId: string | null): CarsPayload {
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

/** Manual spec values a user would type; the wizard no longer pre-fills any. */
export const EXAMPLE_MANUAL_INPUTS = {
  finalDrive: "3.08",
  rim: "18",
  tireAspect: "45",
  tireWidth: "225",
  topGear: "0.64",
} as const;

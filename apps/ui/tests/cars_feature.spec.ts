import { beforeEach, describe, expect, test, vi } from "vitest";
import type { CarLibraryModel } from "../src/api/types";
import { serverStateQueryKeys } from "../src/app/features/server_state_query_keys";
import {
  acceptCarCreation,
  createCarsHarness,
  makeCarsPayload,
  makeGearbox,
  makeModel,
  makeTireOption,
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

function mockLibrary(library: {
  brands?: string[];
  models?: CarLibraryModel[];
  types?: string[];
}): void {
  if (library.brands) {
    api.getCarLibraryBrands.mockResolvedValue({ brands: library.brands });
  }
  if (library.types) {
    api.getCarLibraryTypes.mockResolvedValue({ types: library.types });
  }
  if (library.models) {
    api.getCarLibraryModels.mockResolvedValue({ models: library.models });
  }
}

function createDefaultManualInputs() {
  return {
    finalDrive: "3.08",
    rim: "18",
    tireAspect: "45",
    tireWidth: "225",
    topGear: "0.64",
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("cars feature wizard", () => {
  test("surfaces brand-load failures through render state and focuses the custom-brand input", async () => {
    api.getCarLibraryBrands.mockRejectedValue(new Error("offline"));
    const harness = createCarsHarness();

    await harness.feature.openWizard();

    expect(harness.focuses).toEqual(["close", "custom-brand"]);
    expect(harness.renderState().brandOptions).toEqual({
      message: "settings.wizard.load_failed_brands",
      options: [],
      status: "error",
    });
  });

  test("finishes the manual branch without DOM fixtures and closes the wizard", async () => {
    mockLibrary({ brands: ["BMW"], models: [makeModel()], types: ["SUV"] });
    const requests = acceptCarCreation(api);
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "BMW" });
    await feature.handleWizardAction({ type: "select-type", value: "SUV" });
    await feature.handleWizardAction({
      type: "submit-custom-model",
      value: "X5 M60i",
    });
    harness.updateManualInputs({ tireWidth: "245", topGear: "0.68" });

    await feature.handleWizardAction({ type: "finish" });

    expect(requests).toEqual([
      {
        aspects: expect.objectContaining({
          current_gear_ratio: 0.68,
          final_drive_ratio: 3.08,
          rim_in: 18,
          tire_aspect_pct: 45,
          tire_width_mm: 245,
        }),
        name: "BMW X5 M60i",
        order_reference_status: {
          tire_dimensions_confidence: "user_confirmed",
          current_gear_ratio_confidence: "user_confirmed",
          final_drive_ratio_confidence: "user_confirmed",
          requires_manual_confirmation: false,
          selection_source_status: "manual_entry",
        },
        type: "SUV",
      },
    ]);
    expect(harness.focuses).toContain("manual-tire-width");
    expect(harness.renderState().isOpen).toBe(false);
  });

  test("preserves manual draft values across wizard reopen", async () => {
    mockLibrary({ brands: ["BMW"] });
    const harness = createCarsHarness();

    await harness.feature.openWizard();
    harness.updateManualInputs({ finalDrive: "4.10", topGear: "0.71" });
    await harness.feature.handleWizardAction({ type: "close" });

    await harness.feature.openWizard();

    expect(harness.renderState().manualInputs).toEqual({
      ...createDefaultManualInputs(),
      finalDrive: "4.10",
      topGear: "0.71",
    });
  });

  test("keeps manual gearbox inputs when tire autofill updates only tire fields", async () => {
    const tire = makeTireOption({
      front: {
        width_mm: 275,
        aspect_pct: 40,
        rim_in: 21,
      },
      rear: {
        width_mm: 315,
        aspect_pct: 35,
        rim_in: 21,
      },
      default_axle_for_speed: "rear",
      rim_in: 21,
      tire_aspect_pct: 35,
      tire_width_mm: 315,
    });
    mockLibrary({
      brands: ["BMW"],
      models: [makeModel({ tire_options: [tire] })],
      types: ["SUV"],
    });
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "BMW" });
    await feature.handleWizardAction({ type: "select-type", value: "SUV" });
    harness.updateManualInputs({ finalDrive: "4.10", topGear: "0.71" });
    await feature.handleWizardAction({ type: "select-model", index: 0 });

    expect(harness.renderState().manualInputs).toEqual({
      finalDrive: "4.10",
      rim: "21",
      tireAspect: "40",
      tireWidth: "275",
      topGear: "0.71",
    });
  });

  test("keeps summary data stable while pre-spec manual drafts change", async () => {
    mockLibrary({ brands: ["BMW"] });
    const harness = createCarsHarness();

    await harness.feature.openWizard();

    const initialRenderState = harness.renderState();
    harness.updateManualInputs({ finalDrive: "4.10", topGear: "0.71" });

    const rerenderState = harness.renderState();
    expect(rerenderState.step).toBe(0);
    expect(rerenderState.summaryData).toBe(initialRenderState.summaryData);
    expect(rerenderState.actionHint).toBe(initialRenderState.actionHint);
  });

  test("keeps option references stable while unrelated manual drafts change", async () => {
    mockLibrary({ brands: ["BMW"] });
    const harness = createCarsHarness();

    await harness.feature.openWizard();

    const initialRenderState = harness.renderState();
    harness.updateManualInputs({ finalDrive: "4.10", topGear: "0.71" });

    const rerenderState = harness.renderState();
    expect(rerenderState.brandOptions).toBe(initialRenderState.brandOptions);
    expect(rerenderState.typeOptions).toBe(initialRenderState.typeOptions);
    expect(rerenderState.modelOptions).toBe(initialRenderState.modelOptions);
    expect(rerenderState.variantOptions).toBe(
      initialRenderState.variantOptions,
    );
    expect(rerenderState.tireOptions).toBe(initialRenderState.tireOptions);
    expect(rerenderState.gearboxOptions).toBe(
      initialRenderState.gearboxOptions,
    );
  });

  test("keeps manual input references stable while option state changes", async () => {
    mockLibrary({ brands: ["BMW"], types: ["SUV"] });
    const harness = createCarsHarness();

    await harness.feature.openWizard();

    const initialRenderState = harness.renderState();
    await harness.feature.handleWizardAction({
      type: "select-brand",
      value: "BMW",
    });

    const rerenderState = harness.renderState();
    expect(rerenderState.typeOptions).not.toBe(initialRenderState.typeOptions);
    expect(rerenderState.manualInputs).toBe(initialRenderState.manualInputs);
  });

  test("preserves prior manual edits across sequential field changes", async () => {
    mockLibrary({ brands: ["BMW"], types: ["SUV"] });
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "BMW" });
    await feature.handleWizardAction({ type: "select-type", value: "SUV" });
    await feature.handleWizardAction({
      type: "submit-custom-model",
      value: "X5 M60i",
    });

    harness.updateManualInputs({ tireWidth: "245" });
    harness.updateManualInputs({ topGear: "0.68" });

    expect(harness.renderState().manualInputs).toEqual({
      ...createDefaultManualInputs(),
      tireWidth: "245",
      topGear: "0.68",
    });
  });

  test("refocuses blank custom entries without advancing the wizard", async () => {
    mockLibrary({ brands: ["BMW"] });
    const harness = createCarsHarness();

    await harness.feature.openWizard();
    await harness.feature.handleWizardAction({
      type: "submit-custom-brand",
      value: "   ",
    });

    expect(harness.focuses.at(-1)).toBe("custom-brand");
    expect(harness.renderState().step).toBe(0);
  });

  test("keeps the library branch disabled until a gearbox is chosen and then submits the selected specs", async () => {
    const tire = makeTireOption({
      front: {
        width_mm: 245,
        aspect_pct: 40,
        rim_in: 21,
      },
      rear: {
        width_mm: 275,
        aspect_pct: 35,
        rim_in: 21,
      },
      tire_aspect_pct: 35,
      tire_width_mm: 275,
    });
    mockLibrary({
      brands: ["BMW"],
      models: [makeModel({ gearboxes: [makeGearbox()], tire_options: [tire] })],
      types: ["SUV"],
    });
    const requests = acceptCarCreation(api);
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "BMW" });
    await feature.handleWizardAction({ type: "select-type", value: "SUV" });
    await feature.handleWizardAction({ type: "select-model", index: 0 });

    expect(harness.renderState()).toMatchObject({
      canFinish: false,
      resolvedSpecBranch: null,
      selectedTire: tire,
      step: 4,
    });

    await feature.handleWizardAction({ type: "select-gearbox", index: 0 });
    await feature.handleWizardAction({ type: "finish" });

    expect(requests).toEqual([
      {
        aspects: expect.objectContaining({
          current_gear_ratio: 0.67,
          default_axle_for_speed: "rear",
          final_drive_ratio: 3.15,
          front_rim_in: 21,
          front_tire_aspect_pct: 40,
          front_tire_width_mm: 245,
          rear_rim_in: 21,
          rear_tire_aspect_pct: 35,
          rear_tire_width_mm: 275,
          rim_in: 21,
          tire_aspect_pct: 35,
          tire_width_mm: 275,
        }),
        name: "BMW X5",
        order_reference_status: {
          current_gear_ratio_confidence: "official_exact",
          final_drive_ratio_confidence: "official_exact",
          requires_manual_confirmation: false,
          selection_source_status: "exact_row",
          tire_dimensions_confidence: "official_exact",
          transmission_confidence: "official_exact",
          transmission_name: "8-speed automatic",
        },
        type: "SUV",
      },
    ]);
    expect(harness.focuses).toContain("finish");
    expect(harness.renderState().isOpen).toBe(false);
  });

  test("shows the approximate library action hint when the selected gearbox is approximate", async () => {
    mockLibrary({
      brands: ["BMW"],
      models: [
        makeModel({
          gearboxes: [
            makeGearbox({
              final_drive_ratio_confidence: "family_default",
              requires_manual_confirmation: true,
              source_status: "exact_row",
              top_gear_ratio_confidence: "family_default",
              transmission_confidence: "family_default",
            }),
          ],
          tire_options: [makeTireOption()],
        }),
      ],
      types: ["SUV"],
    });
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "BMW" });
    await feature.handleWizardAction({ type: "select-type", value: "SUV" });
    await feature.handleWizardAction({ type: "select-model", index: 0 });
    await feature.handleWizardAction({ type: "select-gearbox", index: 0 });

    expect(harness.renderState().actionHint).toBe(
      "settings.car.confidence.part_drive · settings.car.confidence.part_gear · settings.car.confidence.part_transmission. settings.car.confidence.review_detail",
    );
  });
});

describe("cars feature saved-car list", () => {
  test("opens the wizard from the list add action", async () => {
    mockLibrary({ brands: ["BMW"] });
    const harness = createCarsHarness();
    harness.feature.bindHandlers();

    harness.listAction({ type: "add", carId: null });
    await vi.waitFor(() => {
      expect(harness.renderState().brandOptions.status).toBe("ready");
    });

    expect(harness.renderState().isOpen).toBe(true);
    expect(harness.focuses).toEqual(["close", "brand-option"]);
  });

  test("dismisses transient creation feedback through typed tab and view callbacks", async () => {
    mockLibrary({ brands: ["Track"] });
    acceptCarCreation(api);
    const harness = createCarsHarness();
    harness.feature.bindHandlers();

    async function createCarThroughWizard(): Promise<void> {
      await harness.feature.openWizard();
      await harness.feature.handleWizardAction({
        type: "submit-custom-brand",
        value: "Track",
      });
      await harness.feature.handleWizardAction({
        type: "submit-custom-type",
        value: "Coupe",
      });
      await harness.feature.handleWizardAction({
        type: "submit-custom-model",
        value: "Demo",
      });
      await harness.feature.handleWizardAction({ type: "finish" });
    }

    await createCarThroughWizard();

    const highlighted = harness.lastListRender();
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

    harness.activeSettingsTabId.value = "analysisTab";

    const dismissedByTab = harness.lastListRender();
    expect(dismissedByTab.guidance).toBeNull();
    expect(dismissedByTab.table?.kind).toBe("rows");
    if (dismissedByTab.table?.kind !== "rows") {
      return;
    }
    expect(dismissedByTab.table.rows[0].isHighlighted).toBe(false);
    expect(dismissedByTab.table.rows[0].highlightedStatusText).toBeNull();

    harness.activeSettingsTabId.value = "carTab";
    await createCarThroughWizard();
    expect(harness.lastListRender().guidance).not.toBeNull();
    harness.activeViewId.value = "dashboardView";

    const dismissedByView = harness.lastListRender();
    expect(dismissedByView.guidance).toBeNull();
    expect(dismissedByView.table?.kind).toBe("rows");
    if (dismissedByView.table?.kind !== "rows") {
      return;
    }
    expect(dismissedByView.table.rows.some((row) => row.isHighlighted)).toBe(
      false,
    );
  });

  test("creates and activates wizard cars through the shared query cache", async () => {
    const createdCarsPayload = {
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
          name: "Volvo XC40 Recharge Twin Motor",
          type: "SUV",
          variant: "Twin Motor",
          aspects: { tire_width_mm: 235, final_drive_ratio: 9.1 },
        },
      ],
      active_car_id: "car-1",
    };
    const activatedCarsPayload = {
      ...createdCarsPayload,
      active_car_id: "car-2",
    };
    const createRequests: Array<Record<string, unknown>> = [];
    const activateRequests: string[] = [];
    api.addSettingsCar.mockImplementation(async (payload) => {
      createRequests.push(payload);
      return createdCarsPayload;
    });
    api.setActiveSettingsCar.mockImplementation(async (carId: string) => {
      activateRequests.push(carId);
      return activatedCarsPayload;
    });
    const gearbox = makeGearbox({
      final_drive_ratio: 9.1,
      final_drive_ratio_confidence: "family_default",
      name: "Single-speed fixed gear",
      requires_manual_confirmation: true,
      top_gear_ratio: 0.71,
      top_gear_ratio_confidence: "family_default",
      transmission_confidence: "family_default",
    });
    const tire = makeTireOption({
      front: { width_mm: 235, aspect_pct: 45, rim_in: 19 },
      rim_in: 19,
      tire_aspect_pct: 45,
      tire_width_mm: 235,
    });
    mockLibrary({
      brands: ["Volvo"],
      models: [
        makeModel({
          brand: "Volvo",
          model: "XC40 Recharge",
          variants: [
            {
              drivetrain: "AWD",
              name: "Twin Motor",
              gearboxes: [gearbox],
              tire_options: [tire],
            },
          ],
        }),
      ],
      types: ["SUV"],
    });
    const harness = createCarsHarness();
    const { appState, feature, queryClient } = harness;
    appState.settings.car.activeVehicleSettings.value = {
      ...appState.settings.car.activeVehicleSettings.value,
      tire_width_mm: 205,
      tire_aspect_pct: 55,
      rim_in: 16,
      final_drive_ratio: 3.9,
      current_gear_ratio: 0.82,
    };

    await feature.openWizard();
    await feature.handleWizardAction({ type: "select-brand", value: "Volvo" });
    await feature.handleWizardAction({ type: "select-type", value: "SUV" });
    await feature.handleWizardAction({ type: "select-model", index: 0 });
    await feature.handleWizardAction({ type: "select-variant", index: 0 });
    await feature.handleWizardAction({ type: "select-gearbox", index: 0 });
    await feature.handleWizardAction({ type: "finish" });

    expect(createRequests).toEqual([
      {
        aspects: expect.objectContaining({
          current_gear_ratio: 0.71,
          final_drive_ratio: 9.1,
          rim_in: 19,
          tire_aspect_pct: 45,
          tire_width_mm: 235,
        }),
        name: "Volvo XC40 Recharge Twin Motor",
        order_reference_status: {
          current_gear_ratio_confidence: "family_default",
          final_drive_ratio_confidence: "family_default",
          requires_manual_confirmation: true,
          selection_source_status: "exact_row",
          tire_dimensions_confidence: "official_exact",
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
    expect(harness.lifecycleCalls).toEqual([
      "syncAnalysisInputs",
      "refreshSpectrumDecorations",
    ]);
    expect(harness.renderState().isOpen).toBe(false);
  });

  test("propagates wizard creation failures and keeps the wizard open", async () => {
    mockLibrary({ brands: ["BMW"] });
    api.addSettingsCar.mockRejectedValue(new Error("network failed"));
    const harness = createCarsHarness();
    const { feature } = harness;

    await feature.openWizard();
    await feature.handleWizardAction({
      type: "submit-custom-brand",
      value: "BMW",
    });
    await feature.handleWizardAction({
      type: "submit-custom-type",
      value: "Coupe",
    });
    await feature.handleWizardAction({
      type: "submit-custom-model",
      value: "M3",
    });
    await feature.handleWizardAction({ type: "finish" });

    expect(harness.errors).toEqual(["settings.car.create_failed"]);
    expect(harness.lifecycleCalls).toEqual([]);
    expect(harness.renderState().isOpen).toBe(true);
    expect(harness.focuses.at(-1)).toBe("finish");
  });

  test("activates a complete saved car and refreshes dependent settings", async () => {
    api.setActiveSettingsCar.mockResolvedValue(makeCarsPayload("car-2"));
    const harness = createCarsHarness();
    harness.feature.bindHandlers();
    harness.seedCars(makeCarsPayload("car-1"));

    harness.listAction({ type: "activate", carId: "car-2" });
    await vi.waitFor(() => {
      expect(harness.appState.settings.car.activeCarId.value).toBe("car-2");
    });

    expect(api.setActiveSettingsCar).toHaveBeenCalledWith("car-2");
    expect(harness.lifecycleCalls).toEqual([
      "syncAnalysisInputs",
      "refreshSpectrumDecorations",
    ]);
  });
});

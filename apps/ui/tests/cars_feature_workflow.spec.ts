import { describe, expect, test } from "vitest";
import {
  createCarsFeatureWorkflow,
  type CarsFeatureFocusTarget,
  type CarsFeatureWorkflowViewPorts,
} from "../src/app/features/cars_feature_workflow";
import type { CarsFeatureManualInputState } from "../src/app/features/cars_manual_input";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarOrderReferenceStatus,
  CarLibraryTireOption,
} from "../src/api/types";
import { createTestQueryClient } from "./query_client_test_support";

type WorkflowHarness = {
  focuses: CarsFeatureFocusTarget[];
};

function createHarness(): WorkflowHarness {
  return {
    focuses: [],
  };
}

function createViewPorts(harness: WorkflowHarness): CarsFeatureWorkflowViewPorts {
  return {
    focus(target): void {
      harness.focuses.push(target);
    },
  };
}

function createTranslator(): (key: string, vars?: Record<string, unknown>) => string {
  return (key, vars) => {
    if (vars?.current && vars?.total && vars?.step) {
      return `${key}:${vars.current}/${vars.total}:${String(vars.step)}`;
    }
    return key;
  };
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

function updateManualInputs(
  workflow: ReturnType<typeof createCarsFeatureWorkflow>,
  updates: Partial<CarsFeatureManualInputState>,
): void {
  for (const [field, value] of Object.entries(updates) as Array<
    [keyof CarsFeatureManualInputState, string]
  >) {
    workflow.handleManualInputChanged(field, value);
  }
}

function makeGearbox(overrides: Partial<CarLibraryGearbox> = {}): CarLibraryGearbox {
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

function makeTireOption(overrides: Partial<CarLibraryTireOption> = {}): CarLibraryTireOption {
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

function makeModel(overrides: Partial<CarLibraryModel> = {}): CarLibraryModel {
  return {
    gearboxes: [],
    model: "X5",
    rim_in: 21,
    tire_aspect_pct: 40,
    tire_options: [],
    tire_width_mm: 275,
    variants: [],
    ...overrides,
  };
}

describe("createCarsFeatureWorkflow", () => {
  test("surfaces brand-load failures through render state and focuses the custom-brand input", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          throw new Error("offline");
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();

    expect(harness.focuses).toEqual(["close", "custom-brand"]);
    expect(workflow.getRenderState().brandOptions).toEqual({
      message: "settings.wizard.load_failed_brands",
      options: [],
      status: "error",
    });
  });

  test("finishes the manual branch without DOM fixtures and closes the wizard", async () => {
    const harness = createHarness();
    const addCalls: Array<{
      aspects: Record<string, number | string>;
      carType: string;
      name: string;
      orderReferenceStatus?: CarOrderReferenceStatus;
      variant?: string;
    }> = [];
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async (name, carType, aspects, orderReferenceStatus, variant) => {
        addCalls.push({ aspects, carType, name, orderReferenceStatus, variant });
      },
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadModels() {
          return [makeModel()];
        },
        async loadTypes() {
          return ["SUV"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    await workflow.selectBrand("BMW");
    await workflow.selectType("SUV");
    await workflow.submitCustomModel("X5 M60i");
    updateManualInputs(workflow, {
      tireWidth: "245",
      topGear: "0.68",
    });

    const closed = await workflow.finishWizard();

    expect(closed).toBe(true);
    expect(addCalls).toEqual([{
      aspects: {
        current_gear_ratio: 0.68,
        final_drive_ratio: 3.08,
        rim_in: 18,
        tire_aspect_pct: 45,
        tire_width_mm: 245,
      },
      carType: "SUV",
      name: "BMW X5 M60i",
      orderReferenceStatus: {
        current_gear_ratio_confidence: "user_confirmed",
        final_drive_ratio_confidence: "user_confirmed",
        requires_manual_confirmation: false,
        selection_source_status: "manual_entry",
      },
      variant: undefined,
    }]);
    expect(harness.focuses).toContain("manual-tire-width");
    expect(workflow.getRenderState().isOpen).toBe(false);
  });

  test("preserves manual draft values across wizard reopen", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    updateManualInputs(workflow, {
      finalDrive: "4.10",
      topGear: "0.71",
    });
    workflow.closeWizard();

    await workflow.openWizard();

    expect(workflow.getRenderState().manualInputs).toEqual({
      ...createDefaultManualInputs(),
      finalDrive: "4.10",
      topGear: "0.71",
    });
  });

  test("keeps manual gearbox inputs when tire autofill updates only tire fields", async () => {
    const harness = createHarness();
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
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadModels() {
          return [makeModel({
            tire_options: [tire],
          })];
        },
        async loadTypes() {
          return ["SUV"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    await workflow.selectBrand("BMW");
    await workflow.selectType("SUV");
    updateManualInputs(workflow, {
      finalDrive: "4.10",
      topGear: "0.71",
    });
    await workflow.selectModel(0);

    expect(workflow.getRenderState().manualInputs).toEqual({
      finalDrive: "4.10",
      rim: "21",
      tireAspect: "40",
      tireWidth: "275",
      topGear: "0.71",
    });
  });

  test("keeps summary data stable while pre-spec manual drafts change", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();

    const initialRenderState = workflow.getRenderState();
    updateManualInputs(workflow, {
      finalDrive: "4.10",
      topGear: "0.71",
    });

    const rerenderState = workflow.getRenderState();
    expect(rerenderState.step).toBe(0);
    expect(rerenderState.summaryData).toBe(initialRenderState.summaryData);
    expect(rerenderState.actionHint).toBe(initialRenderState.actionHint);
  });

  test("keeps option references stable while unrelated manual drafts change", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();

    const initialRenderState = workflow.getRenderState();
    updateManualInputs(workflow, {
      finalDrive: "4.10",
      topGear: "0.71",
    });

    const rerenderState = workflow.getRenderState();
    expect(rerenderState.brandOptions).toBe(initialRenderState.brandOptions);
    expect(rerenderState.typeOptions).toBe(initialRenderState.typeOptions);
    expect(rerenderState.modelOptions).toBe(initialRenderState.modelOptions);
    expect(rerenderState.variantOptions).toBe(initialRenderState.variantOptions);
    expect(rerenderState.tireOptions).toBe(initialRenderState.tireOptions);
    expect(rerenderState.gearboxOptions).toBe(initialRenderState.gearboxOptions);
  });

  test("keeps manual input references stable while option state changes", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadTypes() {
          return ["SUV"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();

    const initialRenderState = workflow.getRenderState();
    await workflow.selectBrand("BMW");

    const rerenderState = workflow.getRenderState();
    expect(rerenderState.typeOptions).not.toBe(initialRenderState.typeOptions);
    expect(rerenderState.manualInputs).toBe(initialRenderState.manualInputs);
  });

  test("preserves prior manual edits across sequential field changes", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadTypes() {
          return ["SUV"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    await workflow.selectBrand("BMW");
    await workflow.selectType("SUV");
    await workflow.submitCustomModel("X5 M60i");

    updateManualInputs(workflow, { tireWidth: "245" });
    updateManualInputs(workflow, { topGear: "0.68" });

    expect(workflow.getRenderState().manualInputs).toEqual({
      ...createDefaultManualInputs(),
      tireWidth: "245",
      topGear: "0.68",
    });
  });

  test("keeps the library branch disabled until a gearbox is chosen and then submits the selected specs", async () => {
    const harness = createHarness();
    const addCalls: Array<{
      aspects: Record<string, number | string>;
      carType: string;
      name: string;
      orderReferenceStatus?: CarOrderReferenceStatus;
      variant?: string;
    }> = [];
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
    const gearbox = makeGearbox();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async (name, carType, aspects, orderReferenceStatus, variant) => {
        addCalls.push({ aspects, carType, name, orderReferenceStatus, variant });
      },
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadModels() {
          return [makeModel({
            gearboxes: [gearbox],
            tire_options: [tire],
          })];
        },
        async loadTypes() {
          return ["SUV"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    await workflow.selectBrand("BMW");
    await workflow.selectType("SUV");
    await workflow.selectModel(0);

    expect(workflow.getRenderState()).toMatchObject({
      canFinish: false,
      resolvedSpecBranch: null,
      selectedTire: tire,
      step: 4,
    });

    workflow.selectGearbox(0);
    const closed = await workflow.finishWizard();

    expect(closed).toBe(true);
    expect(addCalls).toEqual([{
      aspects: {
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
      },
      carType: "SUV",
      name: "BMW X5",
      orderReferenceStatus: {
        current_gear_ratio_confidence: "official_exact",
        final_drive_ratio_confidence: "official_exact",
        requires_manual_confirmation: false,
        selection_source_status: "exact_row",
        transmission_confidence: "official_exact",
        transmission_name: "8-speed automatic",
      },
      variant: undefined,
    }]);
    expect(harness.focuses).toContain("finish");
    expect(workflow.getRenderState().isOpen).toBe(false);
  });

  test("shows the approximate library action hint when the selected gearbox is projected", async () => {
    const harness = createHarness();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadModels() {
          return [makeModel({
            gearboxes: [
              makeGearbox({
                final_drive_ratio_confidence: "family_default",
                requires_manual_confirmation: true,
                source_status: "compat_projection",
                top_gear_ratio_confidence: "family_default",
                transmission_confidence: "family_default",
              }),
            ],
            tire_options: [makeTireOption()],
          })];
        },
        async loadTypes() {
          return ["SUV"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    await workflow.selectBrand("BMW");
    await workflow.selectType("SUV");
    await workflow.selectModel(0);
    workflow.selectGearbox(0);

    expect(workflow.getRenderState().actionHint).toBe(
      "settings.car.confidence.part_drive · settings.car.confidence.part_gear · settings.car.confidence.part_transmission. settings.car.confidence.review_detail",
    );
  });
});

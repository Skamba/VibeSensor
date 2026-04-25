import { describe, expect, test } from "vitest";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
} from "../src/api/types";
import type {
  CarsFeatureRenderState,
} from "../src/app/features/cars_feature_workflow";
import type { CarsFeatureOptionsState } from "../src/app/features/cars_option_state";
import {
  buildCarsWizardRenderModel,
  createClosedCarsWizardRenderModel,
} from "../src/app/views/car_wizard_view";

function createTranslator(): (key: string, vars?: Record<string, unknown>) => string {
  return (key, vars) => {
    if (vars?.current && vars?.total && vars?.step) {
      return `${key}:${vars.current}/${vars.total}:${String(vars.step)}`;
    }
    return key;
  };
}

function createOptionsState<TOption>(
  options: readonly TOption[],
  status: CarsFeatureOptionsState<TOption>["status"] = "ready",
  message: string | null = null,
): CarsFeatureOptionsState<TOption> {
  return {
    message,
    options,
    status,
  };
}

function makeGearbox(overrides: Partial<CarLibraryGearbox> = {}): CarLibraryGearbox {
  return {
    final_drive_ratio: 3.91,
    name: "6-speed",
    top_gear_ratio: 0.82,
    ...overrides,
  };
}

function makeTireOption(overrides: Partial<CarLibraryTireOption> = {}): CarLibraryTireOption {
  return {
    default_axle_for_speed: "rear",
    front: {
      width_mm: 245,
      aspect_pct: 40,
      rim_in: 18,
    },
    name: "Sport",
    rear: null,
    rim_in: 18,
    source_confidence: "official_exact",
    tire_aspect_pct: 40,
    tire_width_mm: 245,
    ...overrides,
  };
}

function makeModel(overrides: Partial<CarLibraryModel> = {}): CarLibraryModel {
  return {
    gearboxes: [],
    model: "Roadster",
    rim_in: 18,
    tire_aspect_pct: 40,
    tire_options: [],
    tire_width_mm: 245,
    variants: [],
    ...overrides,
  };
}

function createRenderState(overrides: Partial<CarsFeatureRenderState> = {}): CarsFeatureRenderState {
  return {
    actionHint: "",
    brandOptions: createOptionsState(["BMW"]),
    canFinish: false,
    gearboxOptions: [],
    isOpen: true,
    manualInputs: {
      finalDrive: "3.08",
      rim: "18",
      tireAspect: "45",
      tireWidth: "225",
      topGear: "0.64",
    },
    modelOptions: createOptionsState([makeModel()]),
    noGearboxesMessage: null,
    resolvedSpecBranch: null,
    selectedGearbox: null,
    selectedTire: null,
    step: 0,
    summaryData: {
      currentStep: 0,
      profileName: null,
      brand: null,
      carType: null,
      model: null,
      variant: null,
      tire: null,
      gearbox: null,
    },
    tireOptions: [],
    typeOptions: createOptionsState(["SUV"]),
    variantOptions: [],
    ...overrides,
  };
}

describe("car wizard view helpers", () => {
  test("createClosedCarsWizardRenderModel preserves the manual-spec defaults before the first open", () => {
    const model = createClosedCarsWizardRenderModel();

    expect(model.isOpen).toBe(false);
    expect(model.manualInputs).toEqual({
      finalDrive: "3.08",
      rim: "18",
      tireAspect: "45",
      tireWidth: "225",
      topGear: "0.64",
    });
    expect(model.finishVisible).toBe(false);
  });

  test("buildCarsWizardRenderModel converts option state and progress metadata into typed sections", () => {
    const model = buildCarsWizardRenderModel(createRenderState({
      brandOptions: createOptionsState(["BMW", "Volvo"]),
      modelOptions: createOptionsState([], "loading", "Loading models"),
      step: 2,
      summaryData: {
        currentStep: 2,
        profileName: null,
        brand: "BMW",
        carType: "SUV",
        model: null,
        variant: null,
        tire: null,
        gearbox: null,
      },
      typeOptions: createOptionsState([], "error", "Types offline"),
    }), {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      t: createTranslator(),
    });

    expect(model.backVisible).toBe(true);
    expect(model.progressText).toBe("settings.car.wizard_progress:3/5:settings.car.step_model_short");
    expect(model.brandOptions.options.map((option) => option.value)).toEqual(["BMW", "Volvo"]);
    expect(model.typeOptions.messageText).toBe("Types offline");
    expect(model.modelOptions.messageText).toBe("Loading models");
    expect(model.summary.rows).toEqual([
      {
        labelText: "settings.car.wizard_summary_brand",
        valueText: "BMW",
      },
      {
        labelText: "settings.car.wizard_summary_type",
        valueText: "SUV",
      },
    ]);
  });

  test("buildCarsWizardRenderModel formats selected library specs and pending summary rows", () => {
    const tire = makeTireOption();
    const gearbox = makeGearbox();

    const model = buildCarsWizardRenderModel(createRenderState({
      actionHint: "Library path selected",
      canFinish: true,
      gearboxOptions: [gearbox],
      resolvedSpecBranch: "library",
      selectedGearbox: gearbox,
      selectedTire: tire,
      step: 4,
      summaryData: {
        currentStep: 4,
        profileName: "BMW Roadster",
        brand: "BMW",
        carType: "Coupe",
        model: "Roadster",
        variant: null,
        tire: "245/40R18",
        gearbox: "6-speed",
      },
      tireOptions: [tire],
      variantOptions: [{
        drivetrain: "AWD",
        engine: "V8",
        name: "Competition",
      }],
    }), {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      t: createTranslator(),
    });

    expect(model.finishVisible).toBe(true);
    expect(model.finishEnabled).toBe(true);
    expect(model.specBranch).toBe("library");
    expect(model.actionHintText).toBe("Library path selected");
    expect(model.tireOptions.options).toEqual([{
      detailText: "245/40R18",
      labelText: "Sport",
      selected: true,
      value: "0",
    }]);
    expect(model.gearboxOptions.options).toEqual([{
      detailText: "FD: 3.91 · Top Gear: 0.82",
      labelText: "6-speed",
      selected: true,
      value: "0",
    }]);
    expect(model.variantOptions.options).toEqual([{
      detailText: "AWD · V8",
      labelText: "Competition",
      selected: false,
      value: "0",
    }]);
    expect(model.summary.profileNameValueText).toBe("BMW Roadster");
    expect(model.summary.rows.at(-1)).toEqual({
      labelText: "settings.car.wizard_summary_gearbox",
      valueText: "6-speed",
    });
  });

  test("buildCarsWizardRenderModel shows front and rear sizes for staggered tire options", () => {
    const tire = makeTireOption({
      front: {
        width_mm: 245,
        aspect_pct: 40,
        rim_in: 19,
      },
      rear: {
        width_mm: 275,
        aspect_pct: 35,
        rim_in: 19,
      },
      rim_in: 19,
      tire_aspect_pct: 35,
      tire_width_mm: 275,
    });

    const model = buildCarsWizardRenderModel(createRenderState({
      selectedTire: tire,
      tireOptions: [tire],
    }), {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      t: createTranslator(),
    });

    expect(model.tireOptions.options).toEqual([{
      detailText: "Front 245/40R19 · Rear 275/35R19",
      labelText: "Sport",
      selected: true,
      value: "0",
    }]);
  });
});

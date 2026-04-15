import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../transport/http_models";
import type { WizardSummaryData } from "../views/car_wizard_view";
import {
  buildWizardCarName,
  buildWizardSummaryData,
  canFinishWizard,
  DEFAULT_CARS_WIZARD_MANUAL_INPUTS,
  createInitialWizardState,
  getResolvedWizardSpecBranch,
  getWizardActionHint,
  readWizardManualGearboxValues,
  readWizardManualTireValues,
  resetWizardState,
  resolveGearboxes,
  resolveTireOptions,
  type WizardSpecBranch,
  type WizardState,
} from "./cars_wizard_state";
import {
  createCarsFeatureTransport,
  type CarsFeatureTransport,
} from "./cars_feature_transport";

export interface CarsFeatureManualInputState {
  finalDrive: string;
  rim: string;
  tireAspect: string;
  tireWidth: string;
  topGear: string;
}

type CarsFeatureOptionsStatus = "idle" | "loading" | "error" | "ready";

export interface CarsFeatureOptionsState<TOption> {
  message: string | null;
  options: readonly TOption[];
  status: CarsFeatureOptionsStatus;
}

export type CarsFeatureFocusTarget =
  | "brand-option"
  | "close"
  | "custom-brand"
  | "custom-model"
  | "custom-type"
  | "finish"
  | "gearbox-option"
  | "manual-final-drive"
  | "manual-rim"
  | "manual-tire-aspect"
  | "manual-tire-width"
  | "manual-top-gear"
  | "model-option"
  | "spec-selection"
  | "type-option"
  | "variant-option";

export interface CarsFeatureRenderState {
  actionHint: string;
  brandOptions: CarsFeatureOptionsState<string>;
  canFinish: boolean;
  gearboxOptions: readonly CarLibraryGearbox[];
  isOpen: boolean;
  manualInputs: CarsFeatureManualInputState;
  modelOptions: CarsFeatureOptionsState<CarLibraryModel>;
  noGearboxesMessage: string | null;
  resolvedSpecBranch: WizardSpecBranch;
  selectedGearbox: CarLibraryGearbox | null;
  selectedTire: CarLibraryTireOption | null;
  step: number;
  summaryData: WizardSummaryData;
  tireOptions: readonly CarLibraryTireOption[];
  typeOptions: CarsFeatureOptionsState<string>;
  variantOptions: readonly CarLibraryVariant[];
}

export interface CarsFeatureWorkflowViewPorts {
  focus(target: CarsFeatureFocusTarget): void;
  render(state: CarsFeatureRenderState): void;
}

export interface CarsFeatureWorkflowDeps {
  addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number>,
    variant?: string,
  ): Promise<void>;
  fmt: (value: number, digits?: number) => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
  transport?: Partial<CarsFeatureTransport>;
  view: CarsFeatureWorkflowViewPorts;
}

export interface CarsFeatureWorkflow {
  closeWizard(): void;
  finishWizard(): Promise<boolean>;
  getRenderState(): CarsFeatureRenderState;
  goBack(): Promise<void>;
  handleManualInputsChanged(inputs: CarsFeatureManualInputState): void;
  openWizard(): Promise<void>;
  selectBrand(value: string): Promise<void>;
  selectGearbox(index: number): void;
  selectModel(index: number): Promise<void>;
  selectTire(index: number): void;
  selectType(value: string): Promise<void>;
  selectVariant(index: number): Promise<void>;
  submitCustomBrand(value: string): Promise<void>;
  submitCustomModel(value: string): Promise<void>;
  submitCustomType(value: string): Promise<void>;
}

function createIdleOptionsState<TOption>(): CarsFeatureOptionsState<TOption> {
  return {
    message: null,
    options: [],
    status: "idle",
  };
}

function createErrorOptionsState<TOption>(message: string): CarsFeatureOptionsState<TOption> {
  return {
    message,
    options: [],
    status: "error",
  };
}

function createLoadingOptionsState<TOption>(message: string): CarsFeatureOptionsState<TOption> {
  return {
    message,
    options: [],
    status: "loading",
  };
}

function createReadyOptionsState<TOption>(options: readonly TOption[]): CarsFeatureOptionsState<TOption> {
  return {
    message: null,
    options: [...options],
    status: "ready",
  };
}

function cloneManualInputs(inputs: CarsFeatureManualInputState): CarsFeatureManualInputState {
  return { ...inputs };
}

function parsePositiveValue(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function missingManualInputFocusTarget(
  inputs: CarsFeatureManualInputState,
): CarsFeatureFocusTarget | null {
  if (parsePositiveValue(inputs.tireWidth) == null) {
    return "manual-tire-width";
  }
  if (parsePositiveValue(inputs.tireAspect) == null) {
    return "manual-tire-aspect";
  }
  if (parsePositiveValue(inputs.rim) == null) {
    return "manual-rim";
  }
  if (parsePositiveValue(inputs.finalDrive) == null) {
    return "manual-final-drive";
  }
  if (parsePositiveValue(inputs.topGear) == null) {
    return "manual-top-gear";
  }
  return null;
}

function tireInputsFromOption(
  option: CarLibraryTireOption,
  current: CarsFeatureManualInputState,
): CarsFeatureManualInputState {
  return {
    ...current,
    rim: String(option.rim_in),
    tireAspect: String(option.tire_aspect_pct),
    tireWidth: String(option.tire_width_mm),
  };
}

export function createCarsFeatureWorkflow(
  deps: CarsFeatureWorkflowDeps,
): CarsFeatureWorkflow {
  const transport = createCarsFeatureTransport(deps.transport);
  const wizardState: WizardState = createInitialWizardState();

  let isOpen = false;
  let manualInputs: CarsFeatureManualInputState = {
    ...DEFAULT_CARS_WIZARD_MANUAL_INPUTS,
  };
  let brandOptions = createIdleOptionsState<string>();
  let typeOptions = createIdleOptionsState<string>();
  let modelOptions = createIdleOptionsState<CarLibraryModel>();
  let variantOptions: CarLibraryVariant[] = [];
  let tireOptions: CarLibraryTireOption[] = [];
  let gearboxOptions: CarLibraryGearbox[] = [];
  let noGearboxesMessage: string | null = null;

  function currentManualValues() {
    return {
      manualGearbox: readWizardManualGearboxValues(wizardState.step, {
        finalDrive: manualInputs.finalDrive,
        topGear: manualInputs.topGear,
      }),
      manualTire: readWizardManualTireValues(wizardState.step, {
        aspect: manualInputs.tireAspect,
        rim: manualInputs.rim,
        width: manualInputs.tireWidth,
      }),
    };
  }

  function getRenderState(): CarsFeatureRenderState {
    const { manualGearbox, manualTire } = currentManualValues();
    return {
      actionHint: wizardState.step === 4
        ? getWizardActionHint(wizardState, {
          fmt: deps.fmt,
          manualGearbox,
          manualTire,
          t: deps.t,
        })
        : "",
      brandOptions: {
        ...brandOptions,
        options: [...brandOptions.options],
      },
      canFinish: canFinishWizard(wizardState, manualTire, manualGearbox),
      gearboxOptions: [...gearboxOptions],
      isOpen,
      manualInputs: cloneManualInputs(manualInputs),
      modelOptions: {
        ...modelOptions,
        options: [...modelOptions.options],
      },
      noGearboxesMessage,
      resolvedSpecBranch: getResolvedWizardSpecBranch(wizardState),
      selectedGearbox: wizardState.selectedGearbox,
      selectedTire: wizardState.selectedTire,
      step: wizardState.step,
      summaryData: buildWizardSummaryData(wizardState, {
        fmt: deps.fmt,
        manualGearbox,
        manualTire,
        t: deps.t,
      }),
      tireOptions: [...tireOptions],
      typeOptions: {
        ...typeOptions,
        options: [...typeOptions.options],
      },
      variantOptions: [...variantOptions],
    };
  }

  function renderCurrentState(): void {
    deps.view.render(getRenderState());
  }

  function resetDownstreamAfterBrandChange(): void {
    wizardState.carType = "";
    wizardState.model = "";
    wizardState.selectedModel = null;
    wizardState.selectedVariant = null;
    wizardState.selectedGearbox = null;
    wizardState.selectedTire = null;
    wizardState.specBranch = null;
    typeOptions = createIdleOptionsState<string>();
    modelOptions = createIdleOptionsState<CarLibraryModel>();
    variantOptions = [];
    tireOptions = [];
    gearboxOptions = [];
    noGearboxesMessage = null;
  }

  function resetDownstreamAfterTypeChange(): void {
    wizardState.model = "";
    wizardState.selectedModel = null;
    wizardState.selectedVariant = null;
    wizardState.selectedGearbox = null;
    wizardState.selectedTire = null;
    wizardState.specBranch = null;
    modelOptions = createIdleOptionsState<CarLibraryModel>();
    variantOptions = [];
    tireOptions = [];
    gearboxOptions = [];
    noGearboxesMessage = null;
  }

  function resetDownstreamAfterModelChange(): void {
    wizardState.selectedVariant = null;
    wizardState.selectedGearbox = null;
    wizardState.selectedTire = null;
    wizardState.specBranch = null;
    variantOptions = [];
    tireOptions = [];
    gearboxOptions = [];
    noGearboxesMessage = null;
  }

  function resetSpecSelections(): void {
    wizardState.selectedGearbox = null;
    wizardState.selectedTire = null;
    wizardState.specBranch = null;
    tireOptions = [];
    gearboxOptions = [];
    noGearboxesMessage = null;
  }

  async function loadBrandStep(): Promise<void> {
    brandOptions = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    renderCurrentState();
    try {
      brandOptions = createReadyOptionsState(await transport.loadBrands());
      renderCurrentState();
      deps.view.focus("brand-option");
    } catch (_err) {
      brandOptions = createErrorOptionsState(deps.t("settings.wizard.load_failed_brands"));
      renderCurrentState();
      deps.view.focus("custom-brand");
    }
  }

  async function loadTypeStep(): Promise<void> {
    typeOptions = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    renderCurrentState();
    try {
      typeOptions = createReadyOptionsState(await transport.loadTypes(wizardState.brand));
      renderCurrentState();
      deps.view.focus("type-option");
    } catch (_err) {
      typeOptions = createErrorOptionsState(deps.t("settings.wizard.load_failed_types"));
      renderCurrentState();
      deps.view.focus("custom-type");
    }
  }

  async function loadModelStep(): Promise<void> {
    modelOptions = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    renderCurrentState();
    try {
      modelOptions = createReadyOptionsState(
        await transport.loadModels(wizardState.brand, wizardState.carType),
      );
      renderCurrentState();
      deps.view.focus("model-option");
    } catch (_err) {
      modelOptions = createErrorOptionsState(deps.t("settings.wizard.load_failed_models"));
      renderCurrentState();
      deps.view.focus("custom-model");
    }
  }

  function loadVariantStep(): void {
    variantOptions = wizardState.selectedModel?.variants || [];
    if (!variantOptions.length) {
      wizardState.step = 4;
      loadSpecsStep();
      return;
    }
    renderCurrentState();
    deps.view.focus("variant-option");
  }

  function loadSpecsStep(): void {
    tireOptions = resolveTireOptions(wizardState.selectedModel, wizardState.selectedVariant);
    gearboxOptions = resolveGearboxes(wizardState.selectedModel, wizardState.selectedVariant);
    noGearboxesMessage = null;

    if (tireOptions.length > 0) {
      const selectedTire = wizardState.selectedTire && tireOptions.includes(wizardState.selectedTire)
        ? wizardState.selectedTire
        : tireOptions[0];
      wizardState.selectedTire = selectedTire;
      manualInputs = tireInputsFromOption(selectedTire, manualInputs);
    } else {
      wizardState.selectedTire = null;
      wizardState.specBranch = "manual";
    }

    if (!gearboxOptions.length) {
      wizardState.selectedGearbox = null;
      wizardState.specBranch = "manual";
      noGearboxesMessage = deps.t("settings.wizard.no_gearboxes");
      renderCurrentState();
      deps.view.focus("manual-tire-width");
      return;
    }

    renderCurrentState();
    deps.view.focus(tireOptions.length > 0 ? "spec-selection" : "gearbox-option");
  }

  async function loadCurrentStep(): Promise<void> {
    renderCurrentState();
    if (wizardState.step === 0) {
      await loadBrandStep();
      return;
    }
    if (wizardState.step === 1) {
      await loadTypeStep();
      return;
    }
    if (wizardState.step === 2) {
      await loadModelStep();
      return;
    }
    if (wizardState.step === 3) {
      loadVariantStep();
      return;
    }
    loadSpecsStep();
  }

  return {
    closeWizard(): void {
      isOpen = false;
      renderCurrentState();
    },

    async finishWizard(): Promise<boolean> {
      const resolvedBranch = getResolvedWizardSpecBranch(wizardState);
      if (resolvedBranch === "library") {
        const tire = wizardState.selectedTire;
        const gearbox = wizardState.selectedGearbox;
        if (!tire) {
          deps.view.focus("spec-selection");
          return false;
        }
        if (!gearbox) {
          deps.view.focus("gearbox-option");
          return false;
        }
        await deps.addCarFromWizard(
          buildWizardCarName(wizardState.brand, wizardState.model, wizardState.selectedVariant),
          wizardState.carType || "Custom",
          {
            current_gear_ratio: gearbox.top_gear_ratio,
            final_drive_ratio: gearbox.final_drive_ratio,
            rim_in: tire.rim_in,
            tire_aspect_pct: tire.tire_aspect_pct,
            tire_width_mm: tire.tire_width_mm,
          },
          wizardState.selectedVariant?.name,
        );
        isOpen = false;
        renderCurrentState();
        return true;
      }

      const missingFocusTarget = missingManualInputFocusTarget(manualInputs);
      if (missingFocusTarget) {
        deps.view.focus(missingFocusTarget);
        return false;
      }

      await deps.addCarFromWizard(
        buildWizardCarName(wizardState.brand, wizardState.model, wizardState.selectedVariant),
        wizardState.carType || "Custom",
        {
          current_gear_ratio: Number(manualInputs.topGear),
          final_drive_ratio: Number(manualInputs.finalDrive),
          rim_in: Number(manualInputs.rim),
          tire_aspect_pct: Number(manualInputs.tireAspect),
          tire_width_mm: Number(manualInputs.tireWidth),
        },
        wizardState.selectedVariant?.name,
      );
      isOpen = false;
      renderCurrentState();
      return true;
    },

    getRenderState,

    async goBack(): Promise<void> {
      if (wizardState.step === 0) {
        return;
      }
      wizardState.step -= 1;
      if (wizardState.step === 3 && !(wizardState.selectedModel?.variants?.length)) {
        wizardState.step = 2;
      }
      await loadCurrentStep();
    },

    handleManualInputsChanged(inputs: CarsFeatureManualInputState): void {
      manualInputs = cloneManualInputs(inputs);
      if (isOpen && wizardState.step === 4) {
        wizardState.specBranch = "manual";
        renderCurrentState();
      }
    },

    async openWizard(): Promise<void> {
      resetWizardState(wizardState);
      manualInputs = cloneManualInputs(manualInputs);
      brandOptions = createIdleOptionsState<string>();
      typeOptions = createIdleOptionsState<string>();
      modelOptions = createIdleOptionsState<CarLibraryModel>();
      variantOptions = [];
      tireOptions = [];
      gearboxOptions = [];
      noGearboxesMessage = null;
      isOpen = true;
      renderCurrentState();
      deps.view.focus("close");
      await loadCurrentStep();
    },

    async selectBrand(value: string): Promise<void> {
      if (!value) {
        return;
      }
      wizardState.brand = value;
      wizardState.step = 1;
      resetDownstreamAfterBrandChange();
      await loadCurrentStep();
    },

    selectGearbox(index: number): void {
      const gearbox = gearboxOptions[index];
      if (!gearbox) {
        return;
      }
      wizardState.selectedGearbox = gearbox;
      wizardState.specBranch = "library";
      renderCurrentState();
      deps.view.focus("finish");
    },

    async selectModel(index: number): Promise<void> {
      const selectedModel = modelOptions.options[index];
      if (!selectedModel) {
        return;
      }
      wizardState.selectedModel = selectedModel;
      wizardState.model = selectedModel.model;
      wizardState.step = 3;
      resetDownstreamAfterModelChange();
      await loadCurrentStep();
    },

    selectTire(index: number): void {
      const selectedTire = tireOptions[index];
      if (!selectedTire) {
        return;
      }
      wizardState.selectedTire = selectedTire;
      manualInputs = tireInputsFromOption(selectedTire, manualInputs);
      renderCurrentState();
    },

    async selectType(value: string): Promise<void> {
      if (!value) {
        return;
      }
      wizardState.carType = value;
      wizardState.step = 2;
      resetDownstreamAfterTypeChange();
      await loadCurrentStep();
    },

    async selectVariant(index: number): Promise<void> {
      const selectedVariant = variantOptions[index];
      if (!selectedVariant) {
        return;
      }
      wizardState.selectedVariant = selectedVariant;
      wizardState.step = 4;
      resetSpecSelections();
      await loadCurrentStep();
    },

    async submitCustomBrand(value: string): Promise<void> {
      const trimmedValue = value.trim();
      if (!trimmedValue) {
        deps.view.focus("custom-brand");
        return;
      }
      wizardState.brand = trimmedValue;
      wizardState.step = 1;
      resetDownstreamAfterBrandChange();
      await loadCurrentStep();
    },

    async submitCustomModel(value: string): Promise<void> {
      const trimmedValue = value.trim();
      if (!trimmedValue) {
        deps.view.focus("custom-model");
        return;
      }
      wizardState.model = trimmedValue;
      wizardState.selectedModel = null;
      wizardState.selectedVariant = null;
      wizardState.selectedGearbox = null;
      wizardState.selectedTire = null;
      wizardState.specBranch = "manual";
      wizardState.step = 4;
      variantOptions = [];
      tireOptions = [];
      gearboxOptions = [];
      noGearboxesMessage = null;
      await loadCurrentStep();
    },

    async submitCustomType(value: string): Promise<void> {
      const trimmedValue = value.trim();
      if (!trimmedValue) {
        deps.view.focus("custom-type");
        return;
      }
      wizardState.carType = trimmedValue;
      wizardState.step = 2;
      resetDownstreamAfterTypeChange();
      await loadCurrentStep();
    },
  };
}

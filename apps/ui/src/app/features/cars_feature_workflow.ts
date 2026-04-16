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
  resolveGearboxes,
  resolveTireOptions,
  type WizardSpecBranch,
  type WizardState,
} from "./cars_wizard_state";
import {
  createCarsFeatureTransport,
  type CarsFeatureTransport,
} from "./cars_feature_transport";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";

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
  readonly renderState: ReadonlySignal<CarsFeatureRenderState>;
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
  const wizardState = signal<WizardState>(createInitialWizardState());
  const isOpen = signal(false);
  const manualFinalDrive = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.finalDrive);
  const manualRim = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.rim);
  const manualTireAspect = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.tireAspect);
  const manualTireWidth = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.tireWidth);
  const manualTopGear = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.topGear);
  const brandOptions = signal(createIdleOptionsState<string>());
  const typeOptions = signal(createIdleOptionsState<string>());
  const modelOptions = signal(createIdleOptionsState<CarLibraryModel>());
  const variantOptions = signal<readonly CarLibraryVariant[]>([]);
  const tireOptions = signal<readonly CarLibraryTireOption[]>([]);
  const gearboxOptions = signal<readonly CarLibraryGearbox[]>([]);
  const noGearboxesMessage = signal<string | null>(null);

  function readManualInputs(): CarsFeatureManualInputState {
    return {
      finalDrive: manualFinalDrive.value,
      rim: manualRim.value,
      tireAspect: manualTireAspect.value,
      tireWidth: manualTireWidth.value,
      topGear: manualTopGear.value,
    };
  }

  function writeManualInputs(inputs: CarsFeatureManualInputState): void {
    manualFinalDrive.value = inputs.finalDrive;
    manualRim.value = inputs.rim;
    manualTireAspect.value = inputs.tireAspect;
    manualTireWidth.value = inputs.tireWidth;
    manualTopGear.value = inputs.topGear;
  }

  function updateWizardState(mutator: (state: WizardState) => void): void {
    const nextState = { ...wizardState.value };
    mutator(nextState);
    wizardState.value = nextState;
  }

  const manualGearbox = computed(() =>
    readWizardManualGearboxValues(wizardState.value.step, {
      finalDrive: manualFinalDrive.value,
      topGear: manualTopGear.value,
    })
  );

  const manualTire = computed(() =>
    readWizardManualTireValues(wizardState.value.step, {
      aspect: manualTireAspect.value,
      rim: manualRim.value,
      width: manualTireWidth.value,
    })
  );

  const resolvedSpecBranch = computed(() => getResolvedWizardSpecBranch(wizardState.value));

  const canFinish = computed(() =>
    canFinishWizard(
      wizardState.value,
      resolvedSpecBranch.value === "manual" ? manualTire.value : null,
      resolvedSpecBranch.value === "manual" ? manualGearbox.value : null,
    )
  );

  const actionHint = computed(() => {
    const state = wizardState.value;
    if (state.step !== 4) {
      return "";
    }
    const branch = resolvedSpecBranch.value;
    return getWizardActionHint(state, {
      fmt: deps.fmt,
      manualGearbox: branch === "manual" ? manualGearbox.value : null,
      manualTire: branch === "manual" ? manualTire.value : null,
      t: deps.t,
    });
  });

  const summaryData = computed<WizardSummaryData>(() => {
    const state = wizardState.value;
    const branch = resolvedSpecBranch.value;
    return buildWizardSummaryData(state, {
      fmt: deps.fmt,
      manualGearbox: branch === "manual" ? manualGearbox.value : null,
      manualTire: branch === "manual" ? manualTire.value : null,
      t: deps.t,
    });
  });

  const renderState = computed<CarsFeatureRenderState>(() => {
    const state = wizardState.value;
    const inputs = readManualInputs();
    const currentBrandOptions = brandOptions.value;
    const currentTypeOptions = typeOptions.value;
    const currentModelOptions = modelOptions.value;
    const currentVariantOptions = variantOptions.value;
    const currentTireOptions = tireOptions.value;
    const currentGearboxOptions = gearboxOptions.value;
    const currentNoGearboxesMessage = noGearboxesMessage.value;
    return {
      actionHint: actionHint.value,
      brandOptions: currentBrandOptions,
      canFinish: canFinish.value,
      gearboxOptions: currentGearboxOptions,
      isOpen: isOpen.value,
      manualInputs: cloneManualInputs(inputs),
      modelOptions: currentModelOptions,
      noGearboxesMessage: currentNoGearboxesMessage,
      resolvedSpecBranch: resolvedSpecBranch.value,
      selectedGearbox: state.selectedGearbox,
      selectedTire: state.selectedTire,
      step: state.step,
      summaryData: summaryData.value,
      tireOptions: currentTireOptions,
      typeOptions: currentTypeOptions,
      variantOptions: currentVariantOptions,
    };
  });

  function getRenderState(): CarsFeatureRenderState {
    return renderState.value;
  }

  function resetDownstreamAfterBrandChange(): void {
    batch(() => {
      updateWizardState((state) => {
        state.carType = "";
        state.model = "";
        state.selectedModel = null;
        state.selectedVariant = null;
        state.selectedGearbox = null;
        state.selectedTire = null;
        state.specBranch = null;
      });
      typeOptions.value = createIdleOptionsState<string>();
      modelOptions.value = createIdleOptionsState<CarLibraryModel>();
      variantOptions.value = [];
      tireOptions.value = [];
      gearboxOptions.value = [];
      noGearboxesMessage.value = null;
    });
  }

  function resetDownstreamAfterTypeChange(): void {
    batch(() => {
      updateWizardState((state) => {
        state.model = "";
        state.selectedModel = null;
        state.selectedVariant = null;
        state.selectedGearbox = null;
        state.selectedTire = null;
        state.specBranch = null;
      });
      modelOptions.value = createIdleOptionsState<CarLibraryModel>();
      variantOptions.value = [];
      tireOptions.value = [];
      gearboxOptions.value = [];
      noGearboxesMessage.value = null;
    });
  }

  function resetDownstreamAfterModelChange(): void {
    batch(() => {
      updateWizardState((state) => {
        state.selectedVariant = null;
        state.selectedGearbox = null;
        state.selectedTire = null;
        state.specBranch = null;
      });
      variantOptions.value = [];
      tireOptions.value = [];
      gearboxOptions.value = [];
      noGearboxesMessage.value = null;
    });
  }

  function resetSpecSelections(): void {
    batch(() => {
      updateWizardState((state) => {
        state.selectedGearbox = null;
        state.selectedTire = null;
        state.specBranch = null;
      });
      tireOptions.value = [];
      gearboxOptions.value = [];
      noGearboxesMessage.value = null;
    });
  }

  async function loadBrandStep(): Promise<void> {
    brandOptions.value = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    try {
      brandOptions.value = createReadyOptionsState(await transport.loadBrands());
      deps.view.focus("brand-option");
    } catch (_err) {
      brandOptions.value = createErrorOptionsState(deps.t("settings.wizard.load_failed_brands"));
      deps.view.focus("custom-brand");
    }
  }

  async function loadTypeStep(): Promise<void> {
    typeOptions.value = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    try {
      typeOptions.value = createReadyOptionsState(await transport.loadTypes(wizardState.value.brand));
      deps.view.focus("type-option");
    } catch (_err) {
      typeOptions.value = createErrorOptionsState(deps.t("settings.wizard.load_failed_types"));
      deps.view.focus("custom-type");
    }
  }

  async function loadModelStep(): Promise<void> {
    modelOptions.value = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    try {
      modelOptions.value = createReadyOptionsState(
        await transport.loadModels(wizardState.value.brand, wizardState.value.carType),
      );
      deps.view.focus("model-option");
    } catch (_err) {
      modelOptions.value = createErrorOptionsState(deps.t("settings.wizard.load_failed_models"));
      deps.view.focus("custom-model");
    }
  }

  function loadVariantStep(): void {
    const nextVariantOptions = wizardState.value.selectedModel?.variants || [];
    variantOptions.value = nextVariantOptions;
    if (!nextVariantOptions.length) {
      updateWizardState((state) => {
        state.step = 4;
      });
      loadSpecsStep();
      return;
    }
    deps.view.focus("variant-option");
  }

  function loadSpecsStep(): void {
    const state = wizardState.value;
    const currentManualInputs = readManualInputs();
    const nextTireOptions = resolveTireOptions(state.selectedModel, state.selectedVariant);
    const nextGearboxOptions = resolveGearboxes(state.selectedModel, state.selectedVariant);
    const nextSelectedTire = nextTireOptions.length > 0
      ? (state.selectedTire && nextTireOptions.includes(state.selectedTire)
        ? state.selectedTire
        : nextTireOptions[0])
      : null;
    const nextManualInputs = nextSelectedTire
      ? tireInputsFromOption(nextSelectedTire, currentManualInputs)
      : currentManualInputs;
    const nextNoGearboxesMessage = nextGearboxOptions.length > 0
      ? null
      : deps.t("settings.wizard.no_gearboxes");

    batch(() => {
      tireOptions.value = nextTireOptions;
      gearboxOptions.value = nextGearboxOptions;
      noGearboxesMessage.value = nextNoGearboxesMessage;
      writeManualInputs(nextManualInputs);
      updateWizardState((nextState) => {
        nextState.selectedTire = nextSelectedTire;
        if (!nextTireOptions.length) {
          nextState.specBranch = "manual";
        }
        if (!nextGearboxOptions.length) {
          nextState.selectedGearbox = null;
          nextState.specBranch = "manual";
        }
      });
    });

    deps.view.focus(
      nextGearboxOptions.length > 0
        ? (nextTireOptions.length > 0 ? "spec-selection" : "gearbox-option")
        : "manual-tire-width",
    );
  }

  async function loadCurrentStep(): Promise<void> {
    if (wizardState.value.step === 0) {
      await loadBrandStep();
      return;
    }
    if (wizardState.value.step === 1) {
      await loadTypeStep();
      return;
    }
    if (wizardState.value.step === 2) {
      await loadModelStep();
      return;
    }
    if (wizardState.value.step === 3) {
      loadVariantStep();
      return;
    }
    loadSpecsStep();
  }

  return {
    closeWizard(): void {
      isOpen.value = false;
    },

    async finishWizard(): Promise<boolean> {
      const state = wizardState.value;
      const inputs = readManualInputs();
      const resolvedBranch = getResolvedWizardSpecBranch(state);
      if (resolvedBranch === "library") {
        const tire = state.selectedTire;
        const gearbox = state.selectedGearbox;
        if (!tire) {
          deps.view.focus("spec-selection");
          return false;
        }
        if (!gearbox) {
          deps.view.focus("gearbox-option");
          return false;
        }
        await deps.addCarFromWizard(
          buildWizardCarName(state.brand, state.model, state.selectedVariant),
          state.carType || "Custom",
          {
            current_gear_ratio: gearbox.top_gear_ratio,
            final_drive_ratio: gearbox.final_drive_ratio,
            rim_in: tire.rim_in,
            tire_aspect_pct: tire.tire_aspect_pct,
            tire_width_mm: tire.tire_width_mm,
          },
          state.selectedVariant?.name,
        );
        isOpen.value = false;
        return true;
      }

      const missingFocusTarget = missingManualInputFocusTarget(inputs);
      if (missingFocusTarget) {
        deps.view.focus(missingFocusTarget);
        return false;
      }

      await deps.addCarFromWizard(
        buildWizardCarName(state.brand, state.model, state.selectedVariant),
        state.carType || "Custom",
        {
          current_gear_ratio: Number(inputs.topGear),
          final_drive_ratio: Number(inputs.finalDrive),
          rim_in: Number(inputs.rim),
          tire_aspect_pct: Number(inputs.tireAspect),
          tire_width_mm: Number(inputs.tireWidth),
        },
        state.selectedVariant?.name,
      );
      isOpen.value = false;
      return true;
    },

    getRenderState,
    renderState,

    async goBack(): Promise<void> {
      if (wizardState.value.step === 0) {
        return;
      }
      updateWizardState((state) => {
        state.step -= 1;
        if (state.step === 3 && !(state.selectedModel?.variants?.length)) {
          state.step = 2;
        }
      });
      await loadCurrentStep();
    },

    handleManualInputsChanged(inputs: CarsFeatureManualInputState): void {
      batch(() => {
        writeManualInputs(inputs);
        if (isOpen.value && wizardState.value.step === 4) {
          updateWizardState((state) => {
            state.specBranch = "manual";
          });
        }
      });
    },

    async openWizard(): Promise<void> {
      batch(() => {
        wizardState.value = createInitialWizardState();
        brandOptions.value = createIdleOptionsState<string>();
        typeOptions.value = createIdleOptionsState<string>();
        modelOptions.value = createIdleOptionsState<CarLibraryModel>();
        variantOptions.value = [];
        tireOptions.value = [];
        gearboxOptions.value = [];
        noGearboxesMessage.value = null;
        isOpen.value = true;
      });
      deps.view.focus("close");
      await loadCurrentStep();
    },

    async selectBrand(value: string): Promise<void> {
      if (!value) {
        return;
      }
      updateWizardState((state) => {
        state.brand = value;
        state.step = 1;
      });
      resetDownstreamAfterBrandChange();
      await loadCurrentStep();
    },

    selectGearbox(index: number): void {
      const gearbox = gearboxOptions.value[index];
      if (!gearbox) {
        return;
      }
      updateWizardState((state) => {
        state.selectedGearbox = gearbox;
        state.specBranch = "library";
      });
      deps.view.focus("finish");
    },

    async selectModel(index: number): Promise<void> {
      const selectedModel = modelOptions.value.options[index];
      if (!selectedModel) {
        return;
      }
      updateWizardState((state) => {
        state.selectedModel = selectedModel;
        state.model = selectedModel.model;
        state.step = 3;
      });
      resetDownstreamAfterModelChange();
      await loadCurrentStep();
    },

    selectTire(index: number): void {
      const selectedTire = tireOptions.value[index];
      if (!selectedTire) {
        return;
      }
      batch(() => {
        updateWizardState((state) => {
          state.selectedTire = selectedTire;
        });
        writeManualInputs(tireInputsFromOption(selectedTire, readManualInputs()));
      });
    },

    async selectType(value: string): Promise<void> {
      if (!value) {
        return;
      }
      updateWizardState((state) => {
        state.carType = value;
        state.step = 2;
      });
      resetDownstreamAfterTypeChange();
      await loadCurrentStep();
    },

    async selectVariant(index: number): Promise<void> {
      const selectedVariant = variantOptions.value[index];
      if (!selectedVariant) {
        return;
      }
      updateWizardState((state) => {
        state.selectedVariant = selectedVariant;
        state.step = 4;
      });
      resetSpecSelections();
      await loadCurrentStep();
    },

    async submitCustomBrand(value: string): Promise<void> {
      const trimmedValue = value.trim();
      if (!trimmedValue) {
        deps.view.focus("custom-brand");
        return;
      }
      updateWizardState((state) => {
        state.brand = trimmedValue;
        state.step = 1;
      });
      resetDownstreamAfterBrandChange();
      await loadCurrentStep();
    },

    async submitCustomModel(value: string): Promise<void> {
      const trimmedValue = value.trim();
      if (!trimmedValue) {
        deps.view.focus("custom-model");
        return;
      }
      batch(() => {
        updateWizardState((state) => {
          state.model = trimmedValue;
          state.selectedModel = null;
          state.selectedVariant = null;
          state.selectedGearbox = null;
          state.selectedTire = null;
          state.specBranch = "manual";
          state.step = 4;
        });
        variantOptions.value = [];
        tireOptions.value = [];
        gearboxOptions.value = [];
        noGearboxesMessage.value = null;
      });
      await loadCurrentStep();
    },

    async submitCustomType(value: string): Promise<void> {
      const trimmedValue = value.trim();
      if (!trimmedValue) {
        deps.view.focus("custom-type");
        return;
      }
      updateWizardState((state) => {
        state.carType = trimmedValue;
        state.step = 2;
      });
      resetDownstreamAfterTypeChange();
      await loadCurrentStep();
    },
  };
}

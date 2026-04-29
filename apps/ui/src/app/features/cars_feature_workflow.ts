import type { QueryClient } from "@tanstack/query-core";

import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarOrderReferenceStatus,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../api";
import {
  createCarsManualInputStore,
  firstMissingManualInputField,
  tireInputsFromOption,
  type CarsFeatureManualInputState,
} from "./cars_manual_input";
import { tireSetupAspectsFromOption } from "./cars_tire_setup";
import {
  createErrorOptionsState,
  createIdleOptionsState,
  createLoadingOptionsState,
  createReadyOptionsState,
  type CarsFeatureOptionsState,
} from "./cars_option_state";
import type { WizardSummaryData } from "../views/car_wizard_view";
import {
  buildWizardCarName,
  buildWizardSummaryData,
  canFinishWizard,
  createInitialWizardState,
  getResolvedWizardSpecBranch,
  getWizardActionHint,
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
import { serverStateQueryKeys } from "./server_state_query_keys";

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

type CarsFeatureOptionsRenderState = Pick<
  CarsFeatureRenderState,
  | "brandOptions"
  | "gearboxOptions"
  | "modelOptions"
  | "noGearboxesMessage"
  | "tireOptions"
  | "typeOptions"
  | "variantOptions"
>;

type CarsFeatureWizardMetaRenderState = Pick<
  CarsFeatureRenderState,
  | "actionHint"
  | "canFinish"
  | "isOpen"
  | "resolvedSpecBranch"
  | "selectedGearbox"
  | "selectedTire"
  | "step"
  | "summaryData"
>;

export interface CarsFeatureWorkflowViewPorts {
  focus(target: CarsFeatureFocusTarget): void;
}

export interface CarsFeatureWorkflowDeps {
  addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number | string>,
    orderReferenceStatus?: CarOrderReferenceStatus,
    variant?: string,
  ): Promise<void>;
  fmt: (value: number, digits?: number) => string;
  queryClient: QueryClient;
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
  handleManualInputChanged(field: keyof CarsFeatureManualInputState, value: string): void;
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

const MANUAL_INPUT_FOCUS_TARGETS: Record<
  keyof CarsFeatureManualInputState,
  CarsFeatureFocusTarget
> = {
  finalDrive: "manual-final-drive",
  rim: "manual-rim",
  tireAspect: "manual-tire-aspect",
  tireWidth: "manual-tire-width",
  topGear: "manual-top-gear",
};

function missingManualInputFocusTarget(
  inputs: CarsFeatureManualInputState,
): CarsFeatureFocusTarget | null {
  const missingField = firstMissingManualInputField(inputs);
  return missingField ? MANUAL_INPUT_FOCUS_TARGETS[missingField] : null;
}

export function createCarsFeatureWorkflow(
  deps: CarsFeatureWorkflowDeps,
): CarsFeatureWorkflow {
  const transport = createCarsFeatureTransport(deps.transport);
  const wizardState = signal<WizardState>(createInitialWizardState());
  const isOpen = signal(false);
  const wizardStep = computed(() => wizardState.value.step);
  const manualInputs = createCarsManualInputStore(wizardStep);
  const brandOptions = signal(createIdleOptionsState<string>());
  const typeOptions = signal(createIdleOptionsState<string>());
  const modelOptions = signal(createIdleOptionsState<CarLibraryModel>());
  const variantOptions = signal<readonly CarLibraryVariant[]>([]);
  const tireOptions = signal<readonly CarLibraryTireOption[]>([]);
  const gearboxOptions = signal<readonly CarLibraryGearbox[]>([]);
  const noGearboxesMessage = signal<string | null>(null);

  function updateWizardState(mutator: (state: WizardState) => void): void {
    const nextState = { ...wizardState.value };
    mutator(nextState);
    wizardState.value = nextState;
  }
  const manualGearbox = manualInputs.manualGearbox;
  const manualTire = manualInputs.manualTire;

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

  const optionsRenderState = computed<CarsFeatureOptionsRenderState>(() => ({
    brandOptions: brandOptions.value,
    gearboxOptions: gearboxOptions.value,
    modelOptions: modelOptions.value,
    noGearboxesMessage: noGearboxesMessage.value,
    tireOptions: tireOptions.value,
    typeOptions: typeOptions.value,
    variantOptions: variantOptions.value,
  }));

  const manualInputRenderState = manualInputs.state;

  const wizardMetaRenderState = computed<CarsFeatureWizardMetaRenderState>(() => {
    const state = wizardState.value;
    return {
      actionHint: actionHint.value,
      canFinish: canFinish.value,
      isOpen: isOpen.value,
      resolvedSpecBranch: resolvedSpecBranch.value,
      selectedGearbox: state.selectedGearbox,
      selectedTire: state.selectedTire,
      step: state.step,
      summaryData: summaryData.value,
    };
  });

  const renderState = computed<CarsFeatureRenderState>(() => {
    const optionsState = optionsRenderState.value;
    const manualInputsState = manualInputRenderState.value;
    const wizardMetaState = wizardMetaRenderState.value;
    return {
      actionHint: wizardMetaState.actionHint,
      brandOptions: optionsState.brandOptions,
      canFinish: wizardMetaState.canFinish,
      gearboxOptions: optionsState.gearboxOptions,
      isOpen: wizardMetaState.isOpen,
      manualInputs: manualInputsState,
      modelOptions: optionsState.modelOptions,
      noGearboxesMessage: optionsState.noGearboxesMessage,
      resolvedSpecBranch: wizardMetaState.resolvedSpecBranch,
      selectedGearbox: wizardMetaState.selectedGearbox,
      selectedTire: wizardMetaState.selectedTire,
      step: wizardMetaState.step,
      summaryData: wizardMetaState.summaryData,
      tireOptions: optionsState.tireOptions,
      typeOptions: optionsState.typeOptions,
      variantOptions: optionsState.variantOptions,
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
      const brands = await deps.queryClient.fetchQuery({
        queryFn: () => transport.loadBrands(),
        queryKey: serverStateQueryKeys.carsWizard.brands(),
        staleTime: 5 * 60 * 1000,
      });
      brandOptions.value = createReadyOptionsState(brands);
      deps.view.focus("brand-option");
    } catch {
      brandOptions.value = createErrorOptionsState(deps.t("settings.wizard.load_failed_brands"));
      deps.view.focus("custom-brand");
    }
  }

  async function loadTypeStep(): Promise<void> {
    typeOptions.value = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    try {
      const types = await deps.queryClient.fetchQuery({
        queryFn: () => transport.loadTypes(wizardState.value.brand),
        queryKey: serverStateQueryKeys.carsWizard.types(wizardState.value.brand),
        staleTime: 5 * 60 * 1000,
      });
      typeOptions.value = createReadyOptionsState(types);
      deps.view.focus("type-option");
    } catch {
      typeOptions.value = createErrorOptionsState(deps.t("settings.wizard.load_failed_types"));
      deps.view.focus("custom-type");
    }
  }

  async function loadModelStep(): Promise<void> {
    modelOptions.value = createLoadingOptionsState(deps.t("settings.wizard.loading"));
    try {
      const models = await deps.queryClient.fetchQuery({
        queryFn: () => transport.loadModels(wizardState.value.brand, wizardState.value.carType),
        queryKey: serverStateQueryKeys.carsWizard.models(
          wizardState.value.brand,
          wizardState.value.carType,
        ),
        staleTime: 5 * 60 * 1000,
      });
      modelOptions.value = createReadyOptionsState(models);
      deps.view.focus("model-option");
    } catch {
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
    const currentManualInputs = manualInputs.state.value;
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
      manualInputs.write(nextManualInputs);
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
      const inputs = manualInputs.state.value;
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
            ...tireSetupAspectsFromOption(tire),
          },
          {
            tire_dimensions_confidence: tire.source_confidence ?? "unverified",
            current_gear_ratio_confidence: gearbox.top_gear_ratio_confidence ?? "unverified",
            final_drive_ratio_confidence: gearbox.final_drive_ratio_confidence ?? "unverified",
            requires_manual_confirmation: gearbox.requires_manual_confirmation ?? true,
            selection_source_status: gearbox.source_status ?? "exact_row",
            transmission_confidence: gearbox.transmission_confidence ?? "unverified",
            transmission_name: gearbox.name,
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
          {
            tire_dimensions_confidence: "user_confirmed",
            current_gear_ratio_confidence: "user_confirmed",
            final_drive_ratio_confidence: "user_confirmed",
            requires_manual_confirmation: false,
          selection_source_status: "manual_entry",
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

    handleManualInputChanged(
      field: keyof CarsFeatureManualInputState,
      value: string,
    ): void {
      batch(() => {
        manualInputs.write({
          ...manualInputs.state.value,
          [field]: value,
        });
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
        manualInputs.write(tireInputsFromOption(selectedTire, manualInputs.state.value));
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

import type { QueryClient } from "@tanstack/query-core";

import {
  addSettingsCar,
  deleteSettingsCar,
  getCarLibraryBrands,
  getCarLibraryModels,
  getCarLibraryTypes,
  setActiveSettingsCar,
} from "../../api";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
  CarOrderReferenceStatus,
  CarRecord,
  CarsPayload,
  CarUpsertRequest,
} from "../../api/types";
import { getCarCompleteness } from "../../car_selection";
import { activeCar, carSelection } from "../../settings_store";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";
import {
  composeVehicleSettings,
  mergeCarAspectSettings,
} from "../../vehicle_settings";
import {
  batch,
  computed,
  effect,
  signal,
  untracked,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";
import {
  buildCarsWizardRenderModel,
  type WizardSummaryData,
} from "../views/car_wizard_view";
import type {
  CarsFeatureInteraction,
  CarsListRenderModel,
  CarsPanelView,
} from "../views/cars_panel";
import {
  buildCarsGuidanceRenderModel,
  createSettingsCarListRenderModelMemo,
  type CarsListAction,
  type CarsListHighlightedFeedback,
} from "../views/settings_car_list_view";
import { tireSetupAspectsFromOption } from "./cars_tire_setup";
import {
  buildWizardCarName,
  buildWizardSummaryData,
  canFinishWizard,
  createCarsManualInputStore,
  createErrorOptionsState,
  createIdleOptionsState,
  createInitialWizardState,
  createLoadingOptionsState,
  createReadyOptionsState,
  firstMissingManualInputField,
  getResolvedWizardSpecBranch,
  getWizardActionHint,
  manualTireMatchesOption,
  resolveGearboxes,
  resolveTireOptions,
  tireInputsFromOption,
  type CarsFeatureManualInputState,
  type CarsFeatureOptionsState,
  type WizardSpecBranch,
  type WizardState,
} from "./cars_wizard_state";
import { applyCarsPayloadToSettings } from "./dashboard_startup_state";
import { serverStateQueryKeys } from "./server_state_query_keys";
import { createWorkflowGenerationGuard } from "./workflow_generation_guard";

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

export interface CarsFeature {
  bindHandlers(): void;
  dispose(): void;
  /** Applies one typed wizard action; the view dispatches the same actions. */
  handleWizardAction(action: CarsFeatureInteraction): Promise<void>;
  openWizard(): Promise<void>;
  readonly wizardRenderState: ReadonlySignal<CarsFeatureRenderState>;
}

const LIBRARY_STALE_TIME_MS = 5 * 60 * 1000;
/** Model label used when manual specs are chosen before any model was named. */
const MANUAL_FALLBACK_MODEL_NAME = "Custom";

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

function copyActiveCarAspects(
  car: CarRecord | null,
  settings: SettingsState,
): void {
  if (!car?.aspects || typeof car.aspects !== "object") {
    return;
  }
  settings.car.activeVehicleSettings.value = mergeCarAspectSettings(
    settings.car.activeVehicleSettings.value,
    car.aspects,
  );
}

/**
 * Car-management controller: owns the saved-car list (query-backed
 * activation/deletion, creation feedback) and the add-car wizard (step
 * transitions, car-library loading, finish validation) behind the typed
 * `CarsPanelView` bridge.
 */
export function createCarsFeature(ctx: {
  settings: SettingsState;
  queryClient: QueryClient;
  panel: CarsPanelView;
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  openAnalysisTab: () => void;
  refreshSpectrumDecorations: () => void;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "fmt">;
}): CarsFeature {
  const { settings, services, queryClient } = ctx;
  const { t } = services;
  const { fmt } = ctx.formatting;

  // ---------------------------------------------------------------------
  // Saved-car list
  // ---------------------------------------------------------------------

  let handlersBound = false;
  let disposeHighlightedCarSync: (() => void) | null = null;
  const highlightedCar = signal<CarsListHighlightedFeedback | null>(null);
  const carsContextVisible = computed(
    () =>
      ctx.activeViewId.value === "settingsView" &&
      ctx.activeSettingsTabId.value === "carTab",
  );
  const buildCarListRenderModel = createSettingsCarListRenderModelMemo();
  let disposed = false;
  let requestGeneration = 0;
  let mutationInFlight = false;

  function beginMutation(): number | null {
    if (disposed || mutationInFlight) {
      return null;
    }
    mutationInFlight = true;
    requestGeneration += 1;
    return requestGeneration;
  }

  function isCurrent(generation: number): boolean {
    return !disposed && generation === requestGeneration;
  }

  ctx.panel.list.model.value = computed<CarsListRenderModel>(() => {
    const carSelectionState = carSelection.value;
    return {
      guidance: buildCarsGuidanceRenderModel({
        carSelectionState,
        highlightedCarFeedback: highlightedCar.value,
        t,
      }),
      table:
        carSelectionState.kind === "loading"
          ? null
          : buildCarListRenderModel({
              activeCarId: settings.car.activeCarId.value,
              cars: settings.car.cars.value,
              highlightedCarId: highlightedCar.value?.carId ?? null,
              fmt,
              t,
            }),
    };
  });

  function clearHighlightedCarFeedback(): void {
    if (!disposed) {
      highlightedCar.value = null;
    }
  }

  function syncCarsPayload(payload: CarsPayload): void {
    if (disposed) {
      return;
    }
    applyCarsPayloadToSettings(settings.car, payload);
    if (
      highlightedCar.value &&
      !settings.car.cars.value.some(
        (car) => car.id === highlightedCar.value?.carId,
      )
    ) {
      highlightedCar.value = null;
    }
  }

  function syncActiveCarToInputs(): void {
    if (disposed) {
      return;
    }
    copyActiveCarAspects(activeCar.value, settings);
  }

  /** Stores a server cars payload in the query cache and settings state. */
  function applyCarsMutationResult(payload: CarsPayload): void {
    queryClient.setQueryData(serverStateQueryKeys.settings.cars(), payload);
    syncCarsPayload(payload);
  }

  function findCar(carId: string): CarRecord | null {
    return settings.car.cars.value.find((entry) => entry.id === carId) ?? null;
  }

  async function createAndActivateCar(
    name: string,
    carType: string,
    aspects: Record<string, number | string>,
    orderReferenceStatus: CarOrderReferenceStatus,
    variant?: string,
  ): Promise<void> {
    const generation = beginMutation();
    if (generation === null) {
      throw new Error("A car settings operation is already in progress.");
    }
    let failureMessageKey = "settings.car.create_failed";
    try {
      const payload: CarUpsertRequest = {
        aspects: {
          ...composeVehicleSettings(
            settings.car.activeVehicleSettings.value,
            settings.analysis.vehicleSettings.value,
          ),
          ...aspects,
        },
        name,
        type: carType,
        order_reference_status: orderReferenceStatus,
      };
      if (variant) {
        payload.variant = variant;
      }
      const createdPayload = await addSettingsCar(payload);
      if (!isCurrent(generation)) {
        throw new Error("Stale car creation result ignored.");
      }
      if (!Array.isArray(createdPayload.cars)) {
        throw new Error("Car creation response did not include cars.");
      }
      applyCarsMutationResult(createdPayload);
      const newCar = createdPayload.cars[createdPayload.cars.length - 1];
      if (!newCar) {
        throw new Error("Car creation response did not include a created car.");
      }
      failureMessageKey = "settings.car.activate_failed";
      const activatedPayload = await setActiveSettingsCar(newCar.id);
      if (!isCurrent(generation)) {
        throw new Error("Stale car activation result ignored.");
      }
      applyCarsMutationResult(activatedPayload);
      syncActiveCarToInputs();
      highlightedCar.value = { carId: newCar.id, carName: newCar.name };
      ctx.refreshSpectrumDecorations();
    } catch (error) {
      if (isCurrent(generation)) {
        services.showError(t(failureMessageKey));
      }
      throw error;
    } finally {
      mutationInFlight = false;
    }
  }

  async function handleActivateCar(carId: string): Promise<void> {
    const car = findCar(carId);
    if (!car) {
      return;
    }
    if (!getCarCompleteness(car).isComplete) {
      services.showError(t("settings.car.activate_incomplete"));
      return;
    }
    const generation = beginMutation();
    if (generation === null) {
      return;
    }
    try {
      const payload = await setActiveSettingsCar(carId);
      if (!isCurrent(generation)) {
        return;
      }
      applyCarsMutationResult(payload);
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      ctx.refreshSpectrumDecorations();
    } catch (_err) {
      if (isCurrent(generation)) {
        services.showError(t("settings.car.activate_failed"));
      }
    } finally {
      mutationInFlight = false;
    }
  }

  async function handleCompleteCar(carId: string): Promise<void> {
    const car = findCar(carId);
    if (!car) {
      return;
    }
    const generation = beginMutation();
    if (generation === null) {
      return;
    }
    try {
      if (car.id !== settings.car.activeCarId.value) {
        const payload = await setActiveSettingsCar(carId);
        if (!isCurrent(generation)) {
          return;
        }
        applyCarsMutationResult(payload);
        syncActiveCarToInputs();
        ctx.refreshSpectrumDecorations();
      }
      if (!isCurrent(generation)) {
        return;
      }
      clearHighlightedCarFeedback();
      ctx.openAnalysisTab();
    } catch (_err) {
      if (isCurrent(generation)) {
        services.showError(t("settings.car.activate_failed"));
      }
    } finally {
      mutationInFlight = false;
    }
  }

  async function handleDeleteCar(carId: string): Promise<void> {
    const car = findCar(carId);
    const confirmed = await services.requestConfirmation(
      t("settings.car.delete_confirm", { name: car?.name || "" }),
    );
    if (disposed || !confirmed) {
      return;
    }
    const generation = beginMutation();
    if (generation === null) {
      return;
    }
    try {
      const payload = await deleteSettingsCar(carId);
      if (!isCurrent(generation)) {
        return;
      }
      applyCarsMutationResult(payload);
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      ctx.refreshSpectrumDecorations();
    } catch (_err) {
      if (isCurrent(generation)) {
        services.showError(t("settings.car.delete_failed"));
      }
    } finally {
      mutationInFlight = false;
    }
  }

  function handleListAction(action: CarsListAction): void {
    if (action.type === "add") {
      void openWizard();
      return;
    }
    if (disposed || !action.carId) {
      return;
    }
    if (action.type === "activate") {
      void handleActivateCar(action.carId);
    } else if (action.type === "complete") {
      void handleCompleteCar(action.carId);
    } else {
      void handleDeleteCar(action.carId);
    }
  }

  // ---------------------------------------------------------------------
  // Add-car wizard
  // ---------------------------------------------------------------------

  const wizardState = signal<WizardState>(createInitialWizardState());
  const isOpen = signal(false);
  const manualInputs = createCarsManualInputStore(
    computed(() => wizardState.value.step),
  );
  const brandOptions = signal(createIdleOptionsState<string>());
  const typeOptions = signal(createIdleOptionsState<string>());
  const modelOptions = signal(createIdleOptionsState<CarLibraryModel>());
  const variantOptions = signal<readonly CarLibraryVariant[]>([]);
  const tireOptions = signal<readonly CarLibraryTireOption[]>([]);
  const gearboxOptions = signal<readonly CarLibraryGearbox[]>([]);
  const noGearboxesMessage = signal<string | null>(null);
  const wizardLoads = createWorkflowGenerationGuard({
    isActive: () => isOpen.value,
  });
  const { manualGearbox, manualTire } = manualInputs;

  function focusWizard(target: CarsFeatureFocusTarget): void {
    ctx.panel.wizard.focus(target);
  }

  function canApplyWizardLoad(
    generation: number,
    matchesState: (state: WizardState) => boolean,
  ): boolean {
    return wizardLoads.isCurrent(generation) && matchesState(wizardState.value);
  }

  function focusIfCurrent(
    generation: number,
    matchesState: (state: WizardState) => boolean,
    target: CarsFeatureFocusTarget,
  ): void {
    if (canApplyWizardLoad(generation, matchesState)) {
      focusWizard(target);
    }
  }

  function updateWizardState(mutator: (state: WizardState) => void): void {
    const nextState = { ...wizardState.value };
    mutator(nextState);
    wizardState.value = nextState;
  }

  const resolvedSpecBranch = computed(() =>
    getResolvedWizardSpecBranch(wizardState.value),
  );
  const canFinish = computed(() =>
    canFinishWizard(
      wizardState.value,
      resolvedSpecBranch.value === "manual" ? manualTire.value : null,
      resolvedSpecBranch.value === "manual" ? manualGearbox.value : null,
    ),
  );
  const actionHint = computed(() => {
    const state = wizardState.value;
    if (state.step !== 4) {
      return "";
    }
    const branch = resolvedSpecBranch.value;
    return getWizardActionHint(state, {
      fmt,
      manualGearbox: branch === "manual" ? manualGearbox.value : null,
      manualTire: branch === "manual" ? manualTire.value : null,
      t,
    });
  });
  const summaryData = computed<WizardSummaryData>(() => {
    const branch = resolvedSpecBranch.value;
    return buildWizardSummaryData(wizardState.value, {
      fmt,
      manualGearbox: branch === "manual" ? manualGearbox.value : null,
      manualTire: branch === "manual" ? manualTire.value : null,
      t,
    });
  });
  // Options and wizard meta are split into separate computeds so manual draft
  // edits keep the option/summary references stable (and vice versa).
  const optionsRenderState = computed(() => ({
    brandOptions: brandOptions.value,
    gearboxOptions: gearboxOptions.value,
    modelOptions: modelOptions.value,
    noGearboxesMessage: noGearboxesMessage.value,
    tireOptions: tireOptions.value,
    typeOptions: typeOptions.value,
    variantOptions: variantOptions.value,
  }));
  const wizardMetaRenderState = computed(() => {
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
  const wizardRenderState = computed<CarsFeatureRenderState>(() => ({
    ...optionsRenderState.value,
    ...wizardMetaRenderState.value,
    manualInputs: manualInputs.state.value,
  }));
  ctx.panel.wizard.model.value = computed(() =>
    buildCarsWizardRenderModel(wizardRenderState.value, { fmt, t }),
  );

  function resetOptionsAfter(
    step: "brand" | "type" | "model" | "variant",
  ): void {
    if (step === "brand") {
      typeOptions.value = createIdleOptionsState<string>();
    }
    if (step === "brand" || step === "type") {
      modelOptions.value = createIdleOptionsState<CarLibraryModel>();
    }
    if (step !== "variant") {
      variantOptions.value = [];
    }
    tireOptions.value = [];
    gearboxOptions.value = [];
    noGearboxesMessage.value = null;
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
      resetOptionsAfter("brand");
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
      resetOptionsAfter("type");
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
      resetOptionsAfter("model");
    });
  }

  function resetSpecSelections(): void {
    batch(() => {
      updateWizardState((state) => {
        state.selectedGearbox = null;
        state.selectedTire = null;
        state.specBranch = null;
      });
      resetOptionsAfter("variant");
    });
  }

  /**
   * Loads one car-library option step through the query cache, ignoring the
   * result when the wizard moved on (closed, navigated, or reloaded) meanwhile.
   */
  async function loadLibraryOptions<TOption>(
    generation: number,
    matchesState: (state: WizardState) => boolean,
    target: Signal<CarsFeatureOptionsState<TOption>>,
    load: {
      queryKey: readonly unknown[];
      queryFn: () => Promise<TOption[]>;
      failedKey: string;
      readyFocus: CarsFeatureFocusTarget;
      failedFocus: CarsFeatureFocusTarget;
    },
  ): Promise<void> {
    if (!canApplyWizardLoad(generation, matchesState)) {
      return;
    }
    target.value = createLoadingOptionsState(t("settings.wizard.loading"));
    try {
      const options = await queryClient.fetchQuery({
        queryFn: load.queryFn,
        queryKey: load.queryKey,
        staleTime: LIBRARY_STALE_TIME_MS,
      });
      if (!canApplyWizardLoad(generation, matchesState)) {
        return;
      }
      target.value = createReadyOptionsState(options);
      focusIfCurrent(generation, matchesState, load.readyFocus);
    } catch {
      if (!canApplyWizardLoad(generation, matchesState)) {
        return;
      }
      target.value = createErrorOptionsState(t(load.failedKey));
      focusIfCurrent(generation, matchesState, load.failedFocus);
    }
  }

  function loadBrandStep(generation: number): Promise<void> {
    return loadLibraryOptions(
      generation,
      (state) => state.step === 0,
      brandOptions,
      {
        queryKey: serverStateQueryKeys.carsWizard.brands(),
        queryFn: async () => (await getCarLibraryBrands()).brands || [],
        failedKey: "settings.wizard.load_failed_brands",
        readyFocus: "brand-option",
        failedFocus: "custom-brand",
      },
    );
  }

  function loadTypeStep(generation: number): Promise<void> {
    const brand = wizardState.value.brand;
    return loadLibraryOptions(
      generation,
      (state) => state.step === 1 && state.brand === brand,
      typeOptions,
      {
        queryKey: serverStateQueryKeys.carsWizard.types(brand),
        queryFn: async () => (await getCarLibraryTypes(brand)).types || [],
        failedKey: "settings.wizard.load_failed_types",
        readyFocus: "type-option",
        failedFocus: "custom-type",
      },
    );
  }

  function loadModelStep(generation: number): Promise<void> {
    const { brand, carType } = wizardState.value;
    return loadLibraryOptions(
      generation,
      (state) =>
        state.step === 2 && state.brand === brand && state.carType === carType,
      modelOptions,
      {
        queryKey: serverStateQueryKeys.carsWizard.models(brand, carType),
        queryFn: async () =>
          (await getCarLibraryModels(brand, carType)).models || [],
        failedKey: "settings.wizard.load_failed_models",
        readyFocus: "model-option",
        failedFocus: "custom-model",
      },
    );
  }

  function loadVariantStep(generation: number): void {
    const selectedModel = wizardState.value.selectedModel;
    const matchesVariantStep = (state: WizardState) =>
      state.step === 3 && state.selectedModel === selectedModel;
    if (!canApplyWizardLoad(generation, matchesVariantStep)) {
      return;
    }
    const nextVariantOptions = selectedModel?.variants || [];
    variantOptions.value = nextVariantOptions;
    if (!nextVariantOptions.length) {
      updateWizardState((state) => {
        state.step = 4;
      });
      loadSpecsStep(generation);
      return;
    }
    focusIfCurrent(generation, matchesVariantStep, "variant-option");
  }

  function loadSpecsStep(generation: number): void {
    const state = wizardState.value;
    const { selectedModel, selectedVariant } = state;
    const matchesSpecsStep = (current: WizardState) =>
      current.step === 4 &&
      current.selectedModel === selectedModel &&
      current.selectedVariant === selectedVariant;
    if (!canApplyWizardLoad(generation, matchesSpecsStep)) {
      return;
    }
    const currentManualInputs = manualInputs.state.value;
    const nextTireOptions = resolveTireOptions(selectedModel, selectedVariant);
    const nextGearboxOptions = resolveGearboxes(selectedModel, selectedVariant);
    const nextSelectedTire =
      nextTireOptions.length > 0
        ? state.selectedTire && nextTireOptions.includes(state.selectedTire)
          ? state.selectedTire
          : nextTireOptions[0]
        : null;
    const nextManualInputs = nextSelectedTire
      ? tireInputsFromOption(nextSelectedTire, currentManualInputs)
      : currentManualInputs;

    batch(() => {
      tireOptions.value = nextTireOptions;
      gearboxOptions.value = nextGearboxOptions;
      noGearboxesMessage.value =
        nextGearboxOptions.length > 0
          ? null
          : t("settings.wizard.no_gearboxes");
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

    focusIfCurrent(
      generation,
      matchesSpecsStep,
      nextGearboxOptions.length > 0
        ? nextTireOptions.length > 0
          ? "spec-selection"
          : "gearbox-option"
        : "manual-tire-width",
    );
  }

  async function loadCurrentStep(): Promise<void> {
    const generation = wizardLoads.begin();
    const step = wizardState.value.step;
    if (step === 0) {
      await loadBrandStep(generation);
    } else if (step === 1) {
      await loadTypeStep(generation);
    } else if (step === 2) {
      await loadModelStep(generation);
    } else if (step === 3) {
      loadVariantStep(generation);
    } else {
      loadSpecsStep(generation);
    }
  }

  async function submitWizardCar(
    aspects: Record<string, number | string>,
    orderReferenceStatus: CarOrderReferenceStatus,
  ): Promise<void> {
    const state = wizardState.value;
    try {
      await createAndActivateCar(
        buildWizardCarName(state.brand, state.model, state.selectedVariant),
        state.carType || "Custom",
        aspects,
        orderReferenceStatus,
        state.selectedVariant?.name,
      );
    } catch {
      focusWizard("finish");
      return;
    }
    isOpen.value = false;
  }

  async function finishWizard(): Promise<void> {
    const state = wizardState.value;
    if (getResolvedWizardSpecBranch(state) === "library") {
      const tire = state.selectedTire;
      const gearbox = state.selectedGearbox;
      if (!tire) {
        focusWizard("spec-selection");
        return;
      }
      if (!gearbox) {
        focusWizard("gearbox-option");
        return;
      }
      await submitWizardCar(
        {
          current_gear_ratio: gearbox.top_gear_ratio,
          final_drive_ratio: gearbox.final_drive_ratio,
          ...tireSetupAspectsFromOption(tire),
        },
        {
          tire_dimensions_confidence: tire.source_confidence ?? "unverified",
          current_gear_ratio_confidence:
            gearbox.top_gear_ratio_confidence ?? "unverified",
          final_drive_ratio_confidence:
            gearbox.final_drive_ratio_confidence ?? "unverified",
          requires_manual_confirmation:
            gearbox.requires_manual_confirmation ?? true,
          selection_source_status: gearbox.source_status ?? "exact_row",
          transmission_confidence:
            gearbox.transmission_confidence ?? "unverified",
          transmission_name: gearbox.name,
        },
      );
      return;
    }

    const inputs = manualInputs.state.value;
    const missingField = firstMissingManualInputField(inputs);
    if (missingField) {
      focusWizard(MANUAL_INPUT_FOCUS_TARGETS[missingField]);
      return;
    }
    // A library tire the user kept keeps its library setup and confidence;
    // only values the user typed are marked user-confirmed.
    const libraryTire =
      state.selectedTire && manualTireMatchesOption(state.selectedTire, inputs)
        ? state.selectedTire
        : null;
    const libraryTireAspects = libraryTire
      ? tireSetupAspectsFromOption(libraryTire)
      : {};
    const keepsLibraryTire = Object.keys(libraryTireAspects).length > 0;
    await submitWizardCar(
      {
        current_gear_ratio: Number(inputs.topGear),
        final_drive_ratio: Number(inputs.finalDrive),
        ...(keepsLibraryTire
          ? libraryTireAspects
          : {
              rim_in: Number(inputs.rim),
              tire_aspect_pct: Number(inputs.tireAspect),
              tire_width_mm: Number(inputs.tireWidth),
            }),
      },
      {
        tire_dimensions_confidence:
          keepsLibraryTire && libraryTire
            ? (libraryTire.source_confidence ?? "unverified")
            : "user_confirmed",
        current_gear_ratio_confidence: "user_confirmed",
        final_drive_ratio_confidence: "user_confirmed",
        requires_manual_confirmation: false,
        selection_source_status: "manual_entry",
      },
    );
  }

  async function openWizard(): Promise<void> {
    batch(() => {
      wizardState.value = createInitialWizardState();
      brandOptions.value = createIdleOptionsState<string>();
      resetOptionsAfter("brand");
      isOpen.value = true;
    });
    focusWizard("close");
    await loadCurrentStep();
  }

  async function goBack(): Promise<void> {
    if (wizardState.value.step === 0) {
      return;
    }
    updateWizardState((state) => {
      state.step -= 1;
      // Skip steps whose prerequisites were never chosen (no variants, or the
      // manual fallback skipped the library before a brand/type was picked).
      if (state.step === 3 && !state.selectedModel?.variants?.length) {
        state.step = 2;
      }
      if (state.step === 2 && !state.carType) {
        state.step = 1;
      }
      if (state.step === 1 && !state.brand) {
        state.step = 0;
      }
    });
    await loadCurrentStep();
  }

  async function selectBrand(brand: string): Promise<void> {
    updateWizardState((state) => {
      state.brand = brand;
      state.step = 1;
    });
    resetDownstreamAfterBrandChange();
    await loadCurrentStep();
  }

  async function selectType(carType: string): Promise<void> {
    updateWizardState((state) => {
      state.carType = carType;
      state.step = 2;
    });
    resetDownstreamAfterTypeChange();
    await loadCurrentStep();
  }

  async function selectModel(index: number): Promise<void> {
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
  }

  async function selectVariant(index: number): Promise<void> {
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
  }

  function selectTire(index: number): void {
    const selectedTire = tireOptions.value[index];
    if (!selectedTire) {
      return;
    }
    batch(() => {
      updateWizardState((state) => {
        state.selectedTire = selectedTire;
      });
      manualInputs.write(
        tireInputsFromOption(selectedTire, manualInputs.state.value),
      );
    });
  }

  function selectGearbox(index: number): void {
    const gearbox = gearboxOptions.value[index];
    if (!gearbox) {
      return;
    }
    updateWizardState((state) => {
      state.selectedGearbox = gearbox;
      state.specBranch = "library";
    });
    focusWizard("finish");
  }

  async function submitCustomModel(model: string): Promise<void> {
    batch(() => {
      updateWizardState((state) => {
        state.model = model;
        state.selectedModel = null;
        state.selectedVariant = null;
        state.selectedGearbox = null;
        state.selectedTire = null;
        state.specBranch = "manual";
        state.step = 4;
      });
      resetOptionsAfter("model");
    });
    await loadCurrentStep();
  }

  /**
   * Leaves the car library (e.g. after a failed library load) and continues
   * on the specs step with manual wheel and gearbox entry, keeping whatever
   * brand and type were already chosen.
   */
  async function continueWithManualSpecs(): Promise<void> {
    await submitCustomModel(
      wizardState.value.model || MANUAL_FALLBACK_MODEL_NAME,
    );
  }

  function handleManualInputChanged(
    field: keyof CarsFeatureManualInputState,
    value: string,
  ): void {
    batch(() => {
      manualInputs.write({ ...manualInputs.state.value, [field]: value });
      if (isOpen.value && wizardState.value.step === 4) {
        updateWizardState((state) => {
          state.specBranch = "manual";
        });
      }
    });
  }

  /** Custom text entries must be non-blank; blank entries refocus the input. */
  function trimmedOrFocus(
    value: string,
    target: CarsFeatureFocusTarget,
  ): string | null {
    const trimmed = value.trim();
    if (!trimmed) {
      focusWizard(target);
      return null;
    }
    return trimmed;
  }

  async function handleWizardAction(
    action: CarsFeatureInteraction,
  ): Promise<void> {
    switch (action.type) {
      case "open":
        return openWizard();
      case "close":
        wizardLoads.invalidate();
        isOpen.value = false;
        return;
      case "back":
        return goBack();
      case "retry-load":
        return loadCurrentStep();
      case "continue-manual":
        return continueWithManualSpecs();
      case "select-brand":
        return action.value ? selectBrand(action.value) : undefined;
      case "select-type":
        return action.value ? selectType(action.value) : undefined;
      case "select-model":
        return selectModel(action.index);
      case "select-variant":
        return selectVariant(action.index);
      case "select-tire":
        return selectTire(action.index);
      case "select-gearbox":
        return selectGearbox(action.index);
      case "submit-custom-brand": {
        const brand = trimmedOrFocus(action.value, "custom-brand");
        return brand ? selectBrand(brand) : undefined;
      }
      case "submit-custom-type": {
        const carType = trimmedOrFocus(action.value, "custom-type");
        return carType ? selectType(carType) : undefined;
      }
      case "submit-custom-model": {
        const model = trimmedOrFocus(action.value, "custom-model");
        return model ? submitCustomModel(model) : undefined;
      }
      case "manual-input-changed":
        return handleManualInputChanged(action.field, action.value);
      case "finish":
        return finishWizard();
    }
  }

  return {
    bindHandlers(): void {
      if (handlersBound) {
        return;
      }
      handlersBound = true;
      disposeHighlightedCarSync = effect(() => {
        if (highlightedCar.value && !carsContextVisible.value) {
          untracked(clearHighlightedCarFeedback);
        }
      });
      ctx.panel.list.actions.value = { onAction: handleListAction };
      ctx.panel.wizard.actions.value = {
        onAction: (action) => {
          void handleWizardAction(action);
        },
      };
    },
    dispose(): void {
      disposed = true;
      requestGeneration += 1;
      mutationInFlight = false;
      disposeHighlightedCarSync?.();
      disposeHighlightedCarSync = null;
    },
    handleWizardAction,
    openWizard,
    wizardRenderState,
  };
}

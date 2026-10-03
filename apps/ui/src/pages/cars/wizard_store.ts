import { batch, computed, type Signal, signal } from "@preact/signals";

import {
  getCarLibraryBrands,
  getCarLibraryModels,
  getCarLibraryTypes,
} from "../../api/car_library";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../api/types";
import { t } from "../../i18n";
import { createAndActivateCar } from "./cars_store";
import {
  carRequest,
  EMPTY_MANUAL_INPUTS,
  INITIAL_WIZARD_STATE,
  type ManualField,
  type ManualInputs,
  resolveGearboxes,
  resolveTireOptions,
  SPECS_STEP,
  tireInputsFromOption,
  type WizardState,
  wizardCarName,
} from "./wizard_model";

export type FocusTarget =
  | "brand-option"
  | "close"
  | "custom-brand"
  | "custom-model"
  | "custom-type"
  | "finish"
  | "gearbox-option"
  | "model-option"
  | "spec-selection"
  | "type-option"
  | "variant-option"
  | ManualField;

export interface LibraryOptions<T> {
  status: "idle" | "loading" | "error" | "ready";
  message: string | null;
  options: readonly T[];
}

function idle<T>(): LibraryOptions<T> {
  return { status: "idle", message: null, options: [] };
}

/** Model label used when manual specs are chosen before any model was named. */
const MANUAL_FALLBACK_MODEL = "Custom";

export const isOpen = signal(false);
export const wizard = signal<WizardState>(INITIAL_WIZARD_STATE);
export const manualInputs = signal<ManualInputs>(EMPTY_MANUAL_INPUTS);
export const brandOptions = signal(idle<string>());
export const typeOptions = signal(idle<string>());
export const modelOptions = signal(idle<CarLibraryModel>());
export const variantOptions = signal<readonly CarLibraryVariant[]>([]);
export const tireOptions = signal<readonly CarLibraryTireOption[]>([]);
export const gearboxOptions = signal<readonly CarLibraryGearbox[]>([]);
export const noGearboxesMessage = signal<string | null>(null);
export const focusRequest = signal<{ target: FocusTarget; seq: number } | null>(
  null,
);
export const step = computed(() => wizard.value.step);

function focus(target: FocusTarget): void {
  focusRequest.value = { target, seq: (focusRequest.peek()?.seq ?? 0) + 1 };
}

function update(patch: Partial<WizardState>): void {
  wizard.value = { ...wizard.value, ...patch };
}

/** Clears every option list after `step`, so stale choices never show. */
function resetOptionsAfter(step: "brand" | "type" | "model" | "variant"): void {
  if (step === "brand") {
    typeOptions.value = idle();
  }
  if (step === "brand" || step === "type") {
    modelOptions.value = idle();
  }
  if (step !== "variant") {
    variantOptions.value = [];
  }
  tireOptions.value = [];
  gearboxOptions.value = [];
  noGearboxesMessage.value = null;
}

// Each load belongs to one wizard step; closing or moving on invalidates it.
let loadGeneration = 0;

function stillCurrent(
  generation: number,
  matches: (s: WizardState) => boolean,
) {
  return isOpen.value && generation === loadGeneration && matches(wizard.value);
}

async function loadLibrary<T>(
  generation: number,
  matches: (s: WizardState) => boolean,
  options: Signal<LibraryOptions<T>>,
  load: () => Promise<readonly T[]>,
  failedKey: string,
  readyFocus: FocusTarget,
  failedFocus: FocusTarget,
): Promise<void> {
  options.value = {
    status: "loading",
    message: t("settings.wizard.loading"),
    options: [],
  };
  try {
    const loaded = await load();
    if (stillCurrent(generation, matches)) {
      options.value = { status: "ready", message: null, options: [...loaded] };
      focus(readyFocus);
    }
  } catch {
    if (stillCurrent(generation, matches)) {
      options.value = { status: "error", message: t(failedKey), options: [] };
      focus(failedFocus);
    }
  }
}

function loadSpecs(generation: number): void {
  const state = wizard.value;
  const tires = resolveTireOptions(state.selectedModel, state.selectedVariant);
  const gearboxes = resolveGearboxes(
    state.selectedModel,
    state.selectedVariant,
  );
  const selectedTire =
    tires.length > 0
      ? state.selectedTire && tires.includes(state.selectedTire)
        ? state.selectedTire
        : tires[0]
      : null;
  batch(() => {
    tireOptions.value = tires;
    gearboxOptions.value = gearboxes;
    noGearboxesMessage.value = gearboxes.length
      ? null
      : t("settings.wizard.no_gearboxes");
    if (selectedTire) {
      manualInputs.value = tireInputsFromOption(
        selectedTire,
        manualInputs.value,
      );
    }
    update({
      selectedTire,
      ...(tires.length && gearboxes.length
        ? {}
        : {
            specBranch: "manual" as const,
            selectedGearbox: gearboxes.length ? state.selectedGearbox : null,
          }),
    });
  });
  if (stillCurrent(generation, (s) => s.step === SPECS_STEP)) {
    focus(
      gearboxes.length
        ? tires.length
          ? "spec-selection"
          : "gearbox-option"
        : "tireWidth",
    );
  }
}

/** Loads whatever the current step needs from the car library. */
export async function loadCurrentStep(): Promise<void> {
  const generation = ++loadGeneration;
  const { step, brand, carType, selectedModel } = wizard.value;
  if (step === 0) {
    await loadLibrary(
      generation,
      (s) => s.step === 0,
      brandOptions,
      async () => (await getCarLibraryBrands()).brands ?? [],
      "settings.wizard.load_failed_brands",
      "brand-option",
      "custom-brand",
    );
  } else if (step === 1) {
    await loadLibrary(
      generation,
      (s) => s.step === 1 && s.brand === brand,
      typeOptions,
      async () => (await getCarLibraryTypes(brand)).types ?? [],
      "settings.wizard.load_failed_types",
      "type-option",
      "custom-type",
    );
  } else if (step === 2) {
    await loadLibrary(
      generation,
      (s) => s.step === 2 && s.brand === brand && s.carType === carType,
      modelOptions,
      async () => (await getCarLibraryModels(brand, carType)).models ?? [],
      "settings.wizard.load_failed_models",
      "model-option",
      "custom-model",
    );
  } else if (step === 3) {
    const variants = selectedModel?.variants ?? [];
    variantOptions.value = variants;
    if (variants.length) {
      focus("variant-option");
    } else {
      update({ step: SPECS_STEP });
      loadSpecs(generation);
    }
  } else {
    loadSpecs(generation);
  }
}

export async function openWizard(): Promise<void> {
  batch(() => {
    wizard.value = INITIAL_WIZARD_STATE;
    brandOptions.value = idle();
    resetOptionsAfter("brand");
    isOpen.value = true;
  });
  focus("close");
  await loadCurrentStep();
}

export function closeWizard(): void {
  loadGeneration += 1;
  isOpen.value = false;
}

export async function goBack(): Promise<void> {
  const state = wizard.value;
  if (state.step === 0) {
    return;
  }
  // Skip steps whose prerequisites were never chosen (no variants, or the
  // manual fallback skipped the library before a brand/type was picked).
  let previous = state.step - 1;
  if (previous === 3 && !state.selectedModel?.variants?.length) previous = 2;
  if (previous === 2 && !state.carType) previous = 1;
  if (previous === 1 && !state.brand) previous = 0;
  update({ step: previous });
  await loadCurrentStep();
}

export async function selectBrand(brand: string): Promise<void> {
  batch(() => {
    update({
      ...INITIAL_WIZARD_STATE,
      brand,
      step: 1,
    });
    resetOptionsAfter("brand");
  });
  await loadCurrentStep();
}

export async function selectType(carType: string): Promise<void> {
  const { brand } = wizard.value;
  batch(() => {
    update({ ...INITIAL_WIZARD_STATE, brand, carType, step: 2 });
    resetOptionsAfter("type");
  });
  await loadCurrentStep();
}

export async function selectModel(index: number): Promise<void> {
  const model = modelOptions.value.options[index];
  if (!model) {
    return;
  }
  batch(() => {
    update({
      selectedModel: model,
      model: model.model,
      step: 3,
      selectedVariant: null,
      selectedGearbox: null,
      selectedTire: null,
      specBranch: null,
    });
    resetOptionsAfter("model");
  });
  await loadCurrentStep();
}

export async function selectVariant(index: number): Promise<void> {
  const variant = variantOptions.value[index];
  if (!variant) {
    return;
  }
  batch(() => {
    update({
      selectedVariant: variant,
      step: SPECS_STEP,
      selectedGearbox: null,
      selectedTire: null,
      specBranch: null,
    });
    resetOptionsAfter("variant");
  });
  await loadCurrentStep();
}

export function selectTire(index: number): void {
  const tire = tireOptions.value[index];
  if (tire) {
    batch(() => {
      update({ selectedTire: tire });
      manualInputs.value = tireInputsFromOption(tire, manualInputs.value);
    });
  }
}

export function selectGearbox(index: number): void {
  const gearbox = gearboxOptions.value[index];
  if (gearbox) {
    update({ selectedGearbox: gearbox, specBranch: "library" });
    focus("finish");
  }
}

/** Custom text entries must be non-blank; blank entries refocus the input. */
export async function submitCustom(
  kind: "brand" | "type" | "model",
  value: string,
): Promise<void> {
  const trimmed = value.trim();
  if (!trimmed) {
    focus(`custom-${kind}`);
    return;
  }
  if (kind === "brand") {
    await selectBrand(trimmed);
  } else if (kind === "type") {
    await selectType(trimmed);
  } else {
    await continueWithManualSpecs(trimmed);
  }
}

/** Leaves the library and finishes with manual specs on the specs step. */
export async function continueWithManualSpecs(
  model = wizard.value.model || MANUAL_FALLBACK_MODEL,
) {
  batch(() => {
    update({
      model,
      selectedModel: null,
      selectedVariant: null,
      selectedGearbox: null,
      selectedTire: null,
      specBranch: "manual",
      step: SPECS_STEP,
    });
    resetOptionsAfter("model");
  });
  await loadCurrentStep();
}

export function editManualInput(field: ManualField, value: string): void {
  batch(() => {
    manualInputs.value = { ...manualInputs.value, [field]: value };
    if (isOpen.value && wizard.value.step === SPECS_STEP) {
      update({ specBranch: "manual" });
    }
  });
}

export async function finishWizard(): Promise<void> {
  const state = wizard.value;
  const request = carRequest(state, manualInputs.value);
  if (!request.ok) {
    focus(request.focus);
    return;
  }
  try {
    await createAndActivateCar({
      name: wizardCarName(state.brand, state.model, state.selectedVariant),
      type: state.carType || "Custom",
      variant: state.selectedVariant?.name,
      aspects: request.aspects,
      status: request.status,
    });
  } catch {
    focus("finish");
    return;
  }
  isOpen.value = false;
}

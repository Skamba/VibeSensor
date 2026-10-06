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
import type { FuelType } from "../../capabilities";
import { fmt } from "../../format";
import { t } from "../../i18n";
import { carSettings } from "../../settings_store";
import { createAndActivateCar, saveCarEdits } from "./cars_store";
import {
  carRequest,
  type DriveLayout,
  type EngineChoice,
  EMPTY_MANUAL_INPUTS,
  editRequest,
  editTarget,
  INITIAL_WIZARD_STATE,
  type ManualField,
  type ManualInputs,
  parseTireSize,
  type RatioField,
  ratioInputsFromGearbox,
  resolveGearboxes,
  resolveTireOptions,
  SPECS_STEP,
  tireInputsFromOption,
  tireOptionForInputs,
  tireSizeFromInputs,
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
  | "tire-size"
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
/**
 * The sidewall-style size the user typed, with the size the three tire fields
 * held right after. The field shows that text while the fields still hold that
 * size; once a tire pick, a prefill or a field edit changes them, it shows theirs.
 */
const tireSizeDraft = signal<{ text: string; size: string } | null>(null);
export const tireSizeText = computed(() => {
  const size = tireSizeFromInputs(manualInputs.value);
  const draft = tireSizeDraft.value;
  return draft?.size === size ? draft.text : size;
});
export const tireSizeUnreadable = computed(() => {
  const text = tireSizeText.value;
  return Boolean(text.trim()) && parseTireSize(text) === null;
});
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

function resetSpecsForm(inputs: ManualInputs): void {
  manualInputs.value = inputs;
  tireSizeDraft.value = null;
}

/**
 * Clears every option list after `step`, so stale choices never show, and the
 * specs: values prefilled for another car must not be saved as the user's.
 */
function resetOptionsAfter(step: "brand" | "type" | "model" | "variant"): void {
  resetSpecsForm(EMPTY_MANUAL_INPUTS);
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
    state.selectedTire && tires.includes(state.selectedTire)
      ? state.selectedTire
      : (tires[0] ?? null);
  // Prefill as much as the library knows: the first tire, and the gearbox
  // when the variant has only one.
  const selectedGearbox =
    state.selectedGearbox && gearboxes.includes(state.selectedGearbox)
      ? state.selectedGearbox
      : gearboxes.length === 1
        ? gearboxes[0]
        : null;
  batch(() => {
    tireOptions.value = tires;
    gearboxOptions.value = gearboxes;
    noGearboxesMessage.value =
      tires.length && !gearboxes.length
        ? t("settings.wizard.no_gearboxes")
        : null;
    let inputs = manualInputs.value;
    if (selectedTire) {
      inputs = tireInputsFromOption(selectedTire, inputs);
    }
    if (selectedGearbox) {
      inputs = ratioInputsFromGearbox(selectedGearbox, inputs);
    }
    manualInputs.value = inputs;
    update({ selectedTire, selectedGearbox });
  });
  if (stillCurrent(generation, (s) => s.step === SPECS_STEP)) {
    focus(
      tires.length
        ? "spec-selection"
        : gearboxes.length
          ? "gearbox-option"
          : "tire-size",
    );
  }
}

/** A typed brand or type with no library data: skip its lists, say so once. */
function skipLibrary<T>(
  options: Signal<LibraryOptions<T>>,
  target: FocusTarget,
) {
  options.value = { status: "ready", message: null, options: [] };
  focus(target);
}

/** Loads whatever the current step needs from the car library. */
export async function loadCurrentStep(): Promise<void> {
  const generation = ++loadGeneration;
  const { step, brand, carType, selectedModel, libraryMiss } = wizard.value;
  if (step === 1 && libraryMiss === "brand") {
    skipLibrary(typeOptions, "custom-type");
  } else if (step === 2 && libraryMiss !== null) {
    skipLibrary(modelOptions, "custom-model");
  } else if (step === 0) {
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

/** Opens a saved car's specs, prefilled with its values and their sources. */
export function openEditor(carId: string): void {
  const car = carSettings.cars.value.find((entry) => entry.id === carId);
  if (!car) {
    return;
  }
  loadGeneration += 1;
  const { target, inputs } = editTarget(car, fmt);
  batch(() => {
    wizard.value = {
      ...INITIAL_WIZARD_STATE,
      step: SPECS_STEP,
      editing: target,
    };
    resetOptionsAfter("brand");
    resetSpecsForm(inputs);
    isOpen.value = true;
  });
  focus("tire-size");
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
  // Back on the type step, a library brand offers its types again.
  const libraryMiss =
    previous === 0 || (previous === 1 && state.libraryMiss === "type")
      ? null
      : state.libraryMiss;
  update({ step: previous, libraryMiss });
  await loadCurrentStep();
}

export async function selectBrand(
  brand: string,
  inLibrary = true,
): Promise<void> {
  batch(() => {
    update({
      ...INITIAL_WIZARD_STATE,
      brand,
      libraryMiss: inLibrary ? null : "brand",
      step: 1,
    });
    resetOptionsAfter("brand");
  });
  await loadCurrentStep();
}

export async function selectType(
  carType: string,
  inLibrary = true,
): Promise<void> {
  const { brand, libraryMiss } = wizard.value;
  batch(() => {
    update({
      ...INITIAL_WIZARD_STATE,
      brand,
      carType,
      libraryMiss: libraryMiss ?? (inLibrary ? null : "type"),
      step: 2,
    });
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
    batch(() => {
      update({ selectedGearbox: gearbox });
      manualInputs.value = ratioInputsFromGearbox(gearbox, manualInputs.value);
    });
    focus("finish");
  }
}

function libraryMatch(options: readonly string[], text: string): string | null {
  const wanted = text.toLowerCase();
  return options.find((option) => option.toLowerCase() === wanted) ?? null;
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
    const { status, options } = brandOptions.value;
    const known = libraryMatch(options, trimmed);
    // Only a loaded brand list proves the library has no data for this brand.
    await selectBrand(known ?? trimmed, known !== null || status !== "ready");
  } else if (kind === "type") {
    const { status, options } = typeOptions.value;
    const known = libraryMatch(options, trimmed);
    await selectType(known ?? trimmed, known !== null || status !== "ready");
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
      step: SPECS_STEP,
    });
    resetOptionsAfter("model");
  });
  await loadCurrentStep();
}

/** Typed specs; the highlighted library tire follows the tire fields' size. */
function setTypedInputs(inputs: ManualInputs): void {
  batch(() => {
    manualInputs.value = inputs;
    const picked = wizard.value.selectedTire;
    const tire = tireOptionForInputs(tireOptions.value, picked, inputs);
    if (tire !== picked) {
      update({ selectedTire: tire });
    }
  });
}

export function editManualInput(field: ManualField, value: string): void {
  setTypedInputs({ ...manualInputs.value, [field]: value });
}

/**
 * The powertrain where the library does not say. An EV has no gearbox ratio,
 * so its (hidden) top gear is cleared rather than saved unseen.
 */
export function selectPowertrain(fuelType: FuelType): void {
  batch(() => {
    update({ fuelType });
    if (fuelType === "EV") {
      editManualInput("topGear", "");
    }
  });
}

/** The drive layout where the library does not say; `null` is "don't know". */
export function selectDriveLayout(driveLayout: DriveLayout): void {
  update({ driveLayout });
}

/** The engine where the library does not say; `null` is "not sure". */
export function selectEngine(engine: EngineChoice): void {
  update({ engine });
}

/** "I don't know": the ratio stays unknown and its check shows "couldn't test". */
export function clearRatio(field: RatioField): void {
  editManualInput(field, "");
}

/**
 * A size typed as on the sidewall ("225/45 R18") fills the three tire fields;
 * clearing it clears them.
 */
export function editTireSize(text: string): void {
  const parsed =
    parseTireSize(text) ??
    (text.trim() ? null : { tireWidth: "", tireAspect: "", rim: "" });
  batch(() => {
    if (parsed) {
      setTypedInputs({ ...manualInputs.value, ...parsed });
    }
    tireSizeDraft.value = {
      text,
      size: tireSizeFromInputs(manualInputs.value),
    };
  });
}

export async function finishWizard(): Promise<void> {
  const state = wizard.value;
  try {
    if (state.editing) {
      const request = editRequest(
        { ...state, editing: state.editing },
        manualInputs.value,
      );
      if (!request.ok) {
        focus(request.focus);
        return;
      }
      if (
        Object.keys(request.aspects).length ||
        request.fuelType ||
        request.driveLayout ||
        request.engineProfile
      ) {
        await saveCarEdits(state.editing.carId, request.aspects, {
          fuelType: request.fuelType,
          driveLayout: request.driveLayout,
          engineProfile: request.engineProfile,
        });
      }
    } else {
      const request = carRequest(state, manualInputs.value);
      if (!request.ok) {
        focus(request.focus);
        return;
      }
      await createAndActivateCar({
        name: wizardCarName(state.brand, state.model, state.selectedVariant),
        type: state.carType || "Custom",
        variant: state.selectedVariant?.name,
        aspects: request.aspects,
        status: request.status,
        fuelType: request.fuelType,
        driveLayout: request.driveLayout,
        finalDriveAxle: request.finalDriveAxle,
        engineProfile: request.engineProfile,
      });
    }
  } catch {
    focus("finish");
    return;
  }
  isOpen.value = false;
}

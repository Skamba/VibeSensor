import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
  CarOrderReferenceStatus,
} from "../../api/types";
import {
  buildGearboxConfidenceHint,
  formatCarLibraryTireOption,
  tireOptionFront,
  tireSetupAspectsFromOption,
} from "./tires";

/** Pure state rules and text for the add-car wizard. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;
type FormatNumber = (value: number, digits?: number) => string;

export const STEP_LABEL_KEYS = [
  "settings.car.step_brand_short",
  "settings.car.step_type_short",
  "settings.car.step_model_short",
  "settings.car.step_variant_short",
  "settings.car.step_specs_short",
] as const;
export const SPECS_STEP = 4;

export type SpecBranch = "library" | "manual" | null;

export interface WizardState {
  step: number;
  brand: string;
  carType: string;
  model: string;
  selectedModel: CarLibraryModel | null;
  selectedVariant: CarLibraryVariant | null;
  selectedGearbox: CarLibraryGearbox | null;
  selectedTire: CarLibraryTireOption | null;
  specBranch: SpecBranch;
}

export interface ManualInputs {
  tireWidth: string;
  tireAspect: string;
  rim: string;
  finalDrive: string;
  topGear: string;
}

export type ManualField = keyof ManualInputs;

// Manual specs start empty: anything saved from this form is sent as
// user-confirmed vehicle data, so it must be a value the user entered (or a
// library value they kept), never a silent default.
export const EMPTY_MANUAL_INPUTS: ManualInputs = {
  tireWidth: "",
  tireAspect: "",
  rim: "",
  finalDrive: "",
  topGear: "",
};

/** Example values shown as input placeholders only. */
export const MANUAL_INPUT_EXAMPLES: ManualInputs = {
  tireWidth: "225",
  tireAspect: "45",
  rim: "18",
  finalDrive: "3.08",
  topGear: "0.64",
};

export const INITIAL_WIZARD_STATE: WizardState = {
  step: 0,
  brand: "",
  carType: "",
  model: "",
  selectedModel: null,
  selectedVariant: null,
  selectedGearbox: null,
  selectedTire: null,
  specBranch: null,
};

export function resolveGearboxes(
  model: CarLibraryModel | null,
  variant: CarLibraryVariant | null,
): CarLibraryGearbox[] {
  return variant?.gearboxes?.length
    ? variant.gearboxes
    : (model?.gearboxes ?? []);
}

export function resolveTireOptions(
  model: CarLibraryModel | null,
  variant: CarLibraryVariant | null,
): CarLibraryTireOption[] {
  return variant?.tire_options?.length
    ? variant.tire_options
    : (model?.tire_options ?? []);
}

export function wizardCarName(
  brand: string,
  model: string,
  variant: CarLibraryVariant | null,
): string {
  const suffix = variant ? ` ${variant.name}` : "";
  return brand
    ? `${brand} ${model || "Custom"}${suffix}`
    : (model || "Custom Car") + suffix;
}

function positive(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** The manual tire and gearbox, when every field holds a positive number. */
function manualSpecs(inputs: ManualInputs): {
  tire: { width: number; aspect: number; rim: number } | null;
  gearbox: { finalDrive: number; topGear: number } | null;
} {
  const [width, aspect, rim] = [
    inputs.tireWidth,
    inputs.tireAspect,
    inputs.rim,
  ].map(positive);
  const [finalDrive, topGear] = [inputs.finalDrive, inputs.topGear].map(
    positive,
  );
  return {
    tire: width && aspect && rim ? { width, aspect, rim } : null,
    gearbox: finalDrive && topGear ? { finalDrive, topGear } : null,
  };
}

export function firstMissingManualField(
  inputs: ManualInputs,
): ManualField | null {
  const order: ManualField[] = [
    "tireWidth",
    "tireAspect",
    "rim",
    "finalDrive",
    "topGear",
  ];
  return order.find((field) => positive(inputs[field]) === null) ?? null;
}

/** True while the manual tire fields still hold the selected library tire. */
function manualTireMatchesOption(
  option: CarLibraryTireOption,
  inputs: ManualInputs,
): boolean {
  const front = tireOptionFront(option);
  return (
    front != null &&
    positive(inputs.tireWidth) === front.width_mm &&
    positive(inputs.tireAspect) === front.aspect_pct &&
    positive(inputs.rim) === front.rim_in
  );
}

export function tireInputsFromOption(
  option: CarLibraryTireOption,
  current: ManualInputs,
): ManualInputs {
  const front = tireOptionFront(option);
  return front
    ? {
        ...current,
        tireWidth: String(front.width_mm),
        tireAspect: String(front.aspect_pct),
        rim: String(front.rim_in),
      }
    : current;
}

/** Library vs manual specs; manual is forced when the library has no tires or gearboxes. */
export function specBranch(state: WizardState): SpecBranch {
  if (state.step !== SPECS_STEP) {
    return null;
  }
  const tires = resolveTireOptions(state.selectedModel, state.selectedVariant);
  const gearboxes = resolveGearboxes(
    state.selectedModel,
    state.selectedVariant,
  );
  return !tires.length || !gearboxes.length ? "manual" : state.specBranch;
}

export function canFinish(state: WizardState, inputs: ManualInputs): boolean {
  const branch = specBranch(state);
  if (branch === "library") {
    return Boolean(state.selectedTire && state.selectedGearbox);
  }
  if (branch === "manual") {
    const specs = manualSpecs(inputs);
    return Boolean(specs.tire && specs.gearbox);
  }
  return false;
}

export function actionHint(
  state: WizardState,
  inputs: ManualInputs,
  t: Translate,
): string {
  if (state.step !== SPECS_STEP) {
    return "";
  }
  const branch = specBranch(state);
  if (branch === "library" && canFinish(state, inputs)) {
    return (
      buildGearboxConfidenceHint(state.selectedGearbox, t) ??
      t("settings.car.finish_library_ready")
    );
  }
  if (branch === "manual") {
    return t(
      canFinish(state, inputs)
        ? "settings.car.finish_manual_ready"
        : "settings.car.finish_manual_missing",
    );
  }
  return t("settings.car.finish_choose_path");
}

export function progressText(step: number, t: Translate): string {
  return t("settings.car.wizard_progress", {
    current: step + 1,
    step: t(STEP_LABEL_KEYS[step] ?? STEP_LABEL_KEYS[0]),
    total: STEP_LABEL_KEYS.length,
  });
}

function rimText(rim: number, fmt: FormatNumber): string {
  return fmt(rim, Number.isInteger(rim) ? 0 : 1);
}

function libraryTireText(
  tire: CarLibraryTireOption | null,
  fmt: FormatNumber,
): string | null {
  const size = tire ? formatCarLibraryTireOption(tire, fmt) : null;
  if (!tire || !size) {
    return null;
  }
  return tire.name ? `${tire.name} · ${size}` : size;
}

/** The "current selection" panel: profile name plus the rows reached so far. */
export function summary(
  state: WizardState,
  inputs: ManualInputs,
  fmt: FormatNumber,
  t: Translate,
): { profileName: string; rows: Array<{ label: string; value: string }> } {
  const pending = t("settings.car.wizard_summary_pending");
  const atSpecs = state.step >= SPECS_STEP;
  const variantImplicit =
    atSpecs &&
    ((!state.selectedModel && Boolean(state.model)) ||
      (state.selectedModel !== null && !state.selectedModel.variants?.length));
  const manual = specBranch(state) === "manual";
  const specs = manualSpecs(inputs);
  const tire =
    manual && specs.tire
      ? t("settings.car.wizard_summary_manual_tire", {
          width: fmt(specs.tire.width, 0),
          aspect: fmt(specs.tire.aspect, 0),
          rim: rimText(specs.tire.rim, fmt),
        })
      : libraryTireText(state.selectedTire, fmt);
  const gearbox = manual
    ? specs.gearbox
      ? t("settings.car.wizard_summary_manual_gearbox", {
          finalDrive: fmt(specs.gearbox.finalDrive, 2),
          topGear: fmt(specs.gearbox.topGear, 2),
        })
      : null
    : (state.selectedGearbox?.name ?? null);
  const rows: Array<[string, string | null, number]> = [
    ["settings.car.wizard_summary_brand", state.brand || null, 1],
    ["settings.car.wizard_summary_type", state.carType || null, 2],
    ["settings.car.wizard_summary_model", state.model || null, 3],
    [
      "settings.car.wizard_summary_variant",
      state.selectedVariant?.name ||
        (variantImplicit ? t("settings.car.wizard_summary_not_needed") : null),
      4,
    ],
    ["settings.car.wizard_summary_tire", tire, 4],
    ["settings.car.wizard_summary_gearbox", gearbox, 4],
  ];
  return {
    profileName: state.model
      ? wizardCarName(state.brand, state.model, state.selectedVariant)
      : pending,
    rows: rows
      .filter(([, value, fromStep]) => value || state.step >= fromStep)
      .map(([labelKey, value]) => ({
        label: t(labelKey),
        value: value ?? pending,
      })),
  };
}

export function gearboxDetail(
  gearbox: CarLibraryGearbox,
  fmt: FormatNumber,
  t: Translate,
): string {
  const finalDrive =
    gearbox.final_drive_ratio === null
      ? t("settings.car.ratio_unknown")
      : fmt(gearbox.final_drive_ratio, 2);
  return `FD: ${finalDrive} · Top Gear: ${fmt(gearbox.top_gear_ratio, 2)}`;
}

export function variantDetail(variant: CarLibraryVariant): string | null {
  return (
    [variant.drivetrain, variant.engine].filter(Boolean).join(" · ") || null
  );
}

export type CarRequest =
  | {
      ok: true;
      /** A `null` ratio is unknown: the car is saved without it. */
      aspects: Record<string, number | string | null>;
      status: CarOrderReferenceStatus;
    }
  | { ok: false; focus: "spec-selection" | "gearbox-option" | ManualField };

/**
 * The car to create from the wizard: library specs carry their source
 * confidence; manual specs are user-confirmed, except a library tire the
 * user kept unchanged.
 */
export function carRequest(
  state: WizardState,
  inputs: ManualInputs,
): CarRequest {
  if (specBranch(state) === "library") {
    const tire = state.selectedTire;
    const gearbox = state.selectedGearbox;
    if (!tire) {
      return { ok: false, focus: "spec-selection" };
    }
    if (!gearbox) {
      return { ok: false, focus: "gearbox-option" };
    }
    return {
      ok: true,
      aspects: {
        current_gear_ratio: gearbox.top_gear_ratio,
        final_drive_ratio: gearbox.final_drive_ratio,
        ...tireSetupAspectsFromOption(tire),
      },
      status: {
        tire_dimensions_confidence: tire.source_confidence ?? "unverified",
        current_gear_ratio_confidence:
          gearbox.top_gear_ratio_confidence ?? "unverified",
        final_drive_ratio_confidence:
          gearbox.final_drive_ratio === null
            ? null
            : (gearbox.final_drive_ratio_confidence ?? "unverified"),
        requires_manual_confirmation:
          gearbox.requires_manual_confirmation ?? true,
        selection_source_status: gearbox.source_status ?? "exact_row",
        transmission_confidence:
          gearbox.transmission_confidence ?? "unverified",
        transmission_name: gearbox.name,
      },
    };
  }
  const missing = firstMissingManualField(inputs);
  if (missing) {
    return { ok: false, focus: missing };
  }
  const keptTire =
    state.selectedTire && manualTireMatchesOption(state.selectedTire, inputs)
      ? state.selectedTire
      : null;
  const keptAspects = keptTire ? tireSetupAspectsFromOption(keptTire) : {};
  const keepsTire = keptTire !== null && Object.keys(keptAspects).length > 0;
  return {
    ok: true,
    aspects: {
      current_gear_ratio: Number(inputs.topGear),
      final_drive_ratio: Number(inputs.finalDrive),
      ...(keepsTire
        ? keptAspects
        : {
            rim_in: Number(inputs.rim),
            tire_aspect_pct: Number(inputs.tireAspect),
            tire_width_mm: Number(inputs.tireWidth),
          }),
    },
    status: {
      tire_dimensions_confidence: keepsTire
        ? (keptTire.source_confidence ?? "unverified")
        : "user_confirmed",
      current_gear_ratio_confidence: "user_confirmed",
      final_drive_ratio_confidence: "user_confirmed",
      requires_manual_confirmation: false,
      selection_source_status: "manual_entry",
    },
  };
}

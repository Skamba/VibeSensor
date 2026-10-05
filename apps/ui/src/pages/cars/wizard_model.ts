import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
  CarOrderReferenceStatus,
  CarRecord,
} from "../../api/types";
import type { FuelType } from "../../capabilities";
import {
  type CarReferences,
  confidenceProvenance,
  isWeak,
  type ProvenanceTier,
  provenanceTier,
  type ReferenceProvenance,
  savedCarReferences,
} from "../../car_references";
import {
  formatCarLibraryTireOption,
  formatSavedCarTireSummary,
  tireOptionFront,
  tireSetupAspectsFromOption,
} from "./tires";

/** Pure state rules and text for the add-car wizard and the car editor. */

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

/** A saved car being edited: the specs it started with and where they came from. */
export interface EditTarget {
  carId: string;
  name: string;
  original: ManualInputs;
  provenance: CarReferences;
  /** The saved front/rear sizes when they differ; editing the tire sets one size. */
  staggeredTire: string | null;
  /** The saved powertrain; `null` when it was never set. */
  fuelType: FuelType;
}

export interface WizardState {
  step: number;
  brand: string;
  carType: string;
  model: string;
  /** Which typed entry is not in the car library, so its lists are skipped. */
  libraryMiss: "brand" | "type" | null;
  selectedModel: CarLibraryModel | null;
  selectedVariant: CarLibraryVariant | null;
  selectedGearbox: CarLibraryGearbox | null;
  selectedTire: CarLibraryTireOption | null;
  editing: EditTarget | null;
  /** The powertrain the user picked where the library does not say. */
  fuelType: FuelType;
}

export interface ManualInputs {
  tireWidth: string;
  tireAspect: string;
  rim: string;
  finalDrive: string;
  topGear: string;
}

export type ManualField = keyof ManualInputs;
export type RatioField = "finalDrive" | "topGear";

// Specs start empty: a value saved from this form is either one the user
// entered or a library value they kept, never a silent default.
export const EMPTY_MANUAL_INPUTS: ManualInputs = {
  tireWidth: "",
  tireAspect: "",
  rim: "",
  finalDrive: "",
  topGear: "",
};

export const INITIAL_WIZARD_STATE: WizardState = {
  step: 0,
  brand: "",
  carType: "",
  model: "",
  libraryMiss: null,
  selectedModel: null,
  selectedVariant: null,
  selectedGearbox: null,
  selectedTire: null,
  editing: null,
  fuelType: null,
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

/** An optional ratio: empty is unknown (`null`); anything else must be positive. */
function ratioInput(text: string): number | null | "invalid" {
  if (!text.trim()) {
    return null;
  }
  return positive(text) ?? "invalid";
}

function ratioText(value: number | null): string {
  return value === null ? "" : String(value);
}

/**
 * Reads a tire size typed as on the sidewall: "225/45 R18", "225/45ZR18",
 * "P225/45R18 94W", "225 45 18" or "225/45-18".
 */
export function parseTireSize(
  text: string,
): Pick<ManualInputs, "tireWidth" | "tireAspect" | "rim"> | null {
  const match =
    /^\s*[a-z]{0,2}\s*(\d{3})\s*[/\s]\s*(\d{2})\s*(?:[a-z]{0,2}\s*-?\s*|-)\s*(\d{2}(?:[.,]\d)?)\b/i.exec(
      text,
    );
  if (!match) {
    return null;
  }
  const [, width, aspect, rim] = match;
  return { tireWidth: width, tireAspect: aspect, rim: rim.replace(",", ".") };
}

function specTire(
  inputs: ManualInputs,
): { width: number; aspect: number; rim: number } | null {
  const [width, aspect, rim] = [
    inputs.tireWidth,
    inputs.tireAspect,
    inputs.rim,
  ].map(positive);
  return width && aspect && rim ? { width, aspect, rim } : null;
}

/** The three tire fields as a sidewall size ("225/45 R18"); empty while incomplete. */
export function tireSizeFromInputs(inputs: ManualInputs): string {
  const tire = specTire(inputs);
  return tire ? `${tire.width}/${tire.aspect} R${tire.rim}` : "";
}

/** The first field that blocks saving: a missing tire value or an unreadable ratio. */
export function firstInvalidField(inputs: ManualInputs): ManualField | null {
  const tire = (["tireWidth", "tireAspect", "rim"] as const).find(
    (field) => positive(inputs[field]) === null,
  );
  if (tire) {
    return tire;
  }
  return (
    (["finalDrive", "topGear"] as const).find(
      (field) => ratioInput(inputs[field]) === "invalid",
    ) ?? null
  );
}

/** True while the tire fields still hold the selected library tire. */
function tireMatchesOption(
  option: CarLibraryTireOption | null,
  inputs: ManualInputs,
): option is CarLibraryTireOption {
  const front = option ? tireOptionFront(option) : null;
  return (
    front != null &&
    positive(inputs.tireWidth) === front.width_mm &&
    positive(inputs.tireAspect) === front.aspect_pct &&
    positive(inputs.rim) === front.rim_in
  );
}

/**
 * The library tire the tire fields hold: the picked one while they still hold
 * its size, else the first option with their size, else none.
 */
export function tireOptionForInputs(
  options: readonly CarLibraryTireOption[],
  picked: CarLibraryTireOption | null,
  inputs: ManualInputs,
): CarLibraryTireOption | null {
  if (tireMatchesOption(picked, inputs)) {
    return picked;
  }
  return options.find((option) => tireMatchesOption(option, inputs)) ?? null;
}

function sameTire(a: ManualInputs, b: ManualInputs): boolean {
  return (["tireWidth", "tireAspect", "rim"] as const).every(
    (field) => positive(a[field]) === positive(b[field]),
  );
}

function sameRatio(a: string, b: string): boolean {
  return ratioInput(a) === ratioInput(b);
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

export function ratioInputsFromGearbox(
  gearbox: CarLibraryGearbox,
  current: ManualInputs,
): ManualInputs {
  return {
    ...current,
    finalDrive: ratioText(gearbox.final_drive_ratio),
    topGear: ratioText(gearbox.top_gear_ratio),
  };
}

/** The editor's starting point for a saved car. */
export function editTarget(
  car: CarRecord,
  fmt: FormatNumber,
): { target: EditTarget; inputs: ManualInputs } {
  const aspects = car.aspects ?? {};
  const pick = (...values: unknown[]) =>
    values.find((value) => positive(value) !== null) as number | undefined;
  const front = {
    width: pick(aspects.front_tire_width_mm, aspects.tire_width_mm),
    aspect: pick(aspects.front_tire_aspect_pct, aspects.tire_aspect_pct),
    rim: pick(aspects.front_rim_in, aspects.rim_in),
  };
  const staggered =
    positive(aspects.rear_tire_width_mm) !== null &&
    (aspects.rear_tire_width_mm !== front.width ||
      aspects.rear_tire_aspect_pct !== front.aspect ||
      aspects.rear_rim_in !== front.rim);
  const inputs: ManualInputs = {
    tireWidth: front.width === undefined ? "" : String(front.width),
    tireAspect: front.aspect === undefined ? "" : String(front.aspect),
    rim: front.rim === undefined ? "" : String(front.rim),
    finalDrive: ratioText(positive(aspects.final_drive_ratio)),
    topGear: ratioText(positive(aspects.current_gear_ratio)),
  };
  return {
    target: {
      carId: car.id,
      name: car.name,
      original: inputs,
      provenance: savedCarReferences(car),
      staggeredTire: staggered
        ? formatSavedCarTireSummary(aspects, fmt, "")
        : null,
      fuelType: car.fuel_type ?? null,
    },
    inputs,
  };
}

/**
 * Where each spec on the form comes from right now: a value kept from the
 * library (or from the saved car) keeps its source; a typed value is the
 * user's; an empty or unreadable one is missing.
 */
export function specProvenance(
  state: WizardState,
  inputs: ManualInputs,
): CarReferences {
  const { editing, selectedGearbox: gearbox } = state;
  const ratio = (
    field: RatioField,
    libraryValue: number | null | undefined,
    libraryConfidence: string | null | undefined,
    saved: ReferenceProvenance | undefined,
  ): ReferenceProvenance => {
    const value = ratioInput(inputs[field]);
    if (value === null || value === "invalid") {
      return "missing";
    }
    if (editing && sameRatio(inputs[field], editing.original[field])) {
      return saved ?? "user_confirmed";
    }
    if (gearbox && libraryValue === value) {
      return confidenceProvenance(libraryConfidence, "unverified");
    }
    return "user_confirmed";
  };
  let tire: ReferenceProvenance;
  if (!specTire(inputs)) {
    tire = "missing";
  } else if (editing && sameTire(inputs, editing.original)) {
    tire = editing.provenance.tire;
  } else if (tireMatchesOption(state.selectedTire, inputs)) {
    tire = confidenceProvenance(
      state.selectedTire.source_confidence,
      "unverified",
    );
  } else {
    tire = "user_confirmed";
  }
  return {
    tire,
    finalDrive: ratio(
      "finalDrive",
      gearbox?.final_drive_ratio,
      gearbox?.final_drive_ratio_confidence,
      editing?.provenance.finalDrive,
    ),
    topGear: ratio(
      "topGear",
      gearbox?.top_gear_ratio,
      gearbox?.top_gear_ratio_confidence,
      editing?.provenance.topGear,
    ),
  };
}

export function canFinish(state: WizardState, inputs: ManualInputs): boolean {
  return state.step === SPECS_STEP && firstInvalidField(inputs) === null;
}

/** The consequence of the library estimates in the specs, or `null` without any. */
export function estimateNoteKey(
  refs: CarReferences,
  fuelType: FuelType,
): string | null {
  const finalDrive = isWeak(refs.finalDrive);
  // An EV has no gearbox ratio to estimate: its top gear is not used.
  const topGear = fuelType !== "EV" && isWeak(refs.topGear);
  if (finalDrive && topGear) {
    return "settings.car.estimate.both";
  }
  if (finalDrive) {
    return fuelType === "EV"
      ? "settings.car.estimate.final_drive_ev"
      : "settings.car.estimate.final_drive";
  }
  return topGear ? "settings.car.estimate.top_gear" : null;
}

export function actionHint(
  state: WizardState,
  inputs: ManualInputs,
  gearboxCount: number,
  t: Translate,
): string {
  if (state.step !== SPECS_STEP) {
    return "";
  }
  const invalid = firstInvalidField(inputs);
  if (invalid === "finalDrive" || invalid === "topGear") {
    return t("settings.car.finish_ratio_invalid");
  }
  if (invalid) {
    return t("settings.car.finish_needs_tire");
  }
  const refs = specProvenance(state, inputs);
  const estimate = estimateNoteKey(refs, wizardFuelType(state));
  if (estimate) {
    return `${t(estimate)} ${t("settings.car.estimate.edit_hint")}`;
  }
  if (
    !state.editing &&
    gearboxCount > 0 &&
    !state.selectedGearbox &&
    refs.finalDrive === "missing" &&
    (refs.topGear === "missing" || wizardFuelType(state) === "EV")
  ) {
    return t(
      wizardFuelType(state) === "EV"
        ? "settings.car.finish_pick_gearbox_ev"
        : "settings.car.finish_pick_gearbox",
    );
  }
  return t(
    state.editing
      ? "settings.car.finish_edit_ready"
      : "settings.car.finish_ready",
  );
}

/**
 * What was picked on the steps before this one (brand, type, model, variant),
 * for the header trail; a pick left over from a later step after Back is not
 * shown.
 */
export function selectionTrail(state: WizardState): string[] {
  return [
    state.brand,
    state.carType,
    state.model,
    state.selectedVariant?.name ?? "",
  ].filter((value, stepIndex) => value && stepIndex < state.step);
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

function tireSummary(
  state: WizardState,
  inputs: ManualInputs,
  fmt: FormatNumber,
  t: Translate,
): string | null {
  const tire = specTire(inputs);
  if (!tire) {
    return null;
  }
  const kept = state.selectedTire;
  if (tireMatchesOption(kept, inputs)) {
    const size = formatCarLibraryTireOption(kept, fmt);
    if (size) {
      return kept.name ? `${kept.name} · ${size}` : size;
    }
  }
  return t("settings.car.wizard_summary_manual_tire", {
    width: fmt(tire.width, 0),
    aspect: fmt(tire.aspect, 0),
    rim: rimText(tire.rim, fmt),
  });
}

function gearboxSummary(
  state: WizardState,
  inputs: ManualInputs,
  fmt: FormatNumber,
  t: Translate,
): string | null {
  const ratio = (field: RatioField) => {
    const value = ratioInput(inputs[field]);
    return typeof value === "number"
      ? fmt(value, 2)
      : t("settings.car.ratio_unknown");
  };
  if (state.step < SPECS_STEP) {
    return null;
  }
  const ratios =
    wizardFuelType(state) === "EV"
      ? t("settings.car.wizard_summary_ev_gearbox", {
          finalDrive: ratio("finalDrive"),
        })
      : t("settings.car.wizard_summary_manual_gearbox", {
          finalDrive: ratio("finalDrive"),
          topGear: ratio("topGear"),
        });
  return state.selectedGearbox
    ? `${state.selectedGearbox.name} · ${ratios}`
    : ratios;
}

/** The "current selection" panel: profile name plus the rows reached so far. */
export function summary(
  state: WizardState,
  inputs: ManualInputs,
  fmt: FormatNumber,
  t: Translate,
): { profileName: string; rows: Array<{ label: string; value: string }> } {
  const pending = t("settings.car.wizard_summary_pending");
  const specRows: Array<[string, string | null, number]> = [
    ["settings.car.wizard_summary_tire", tireSummary(state, inputs, fmt, t), 4],
    [
      "settings.car.wizard_summary_gearbox",
      gearboxSummary(state, inputs, fmt, t),
      4,
    ],
  ];
  if (state.editing) {
    return {
      profileName: state.editing.name,
      rows: specRows.map(([labelKey, value]) => ({
        label: t(labelKey),
        value: value ?? pending,
      })),
    };
  }
  const atSpecs = state.step >= SPECS_STEP;
  const variantImplicit =
    atSpecs &&
    ((!state.selectedModel && Boolean(state.model)) ||
      (state.selectedModel !== null && !state.selectedModel.variants?.length));
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
    ...specRows,
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

export interface RatioPart {
  text: string;
  tier: ProvenanceTier;
}

/** A gearbox option's ratios, each with its confidence chip. */
export function gearboxParts(
  gearbox: CarLibraryGearbox,
  fmt: FormatNumber,
  t: Translate,
): RatioPart[] {
  const part = (
    key: string,
    value: number | null,
    confidence: string | null | undefined,
  ): RatioPart => {
    const provenance =
      value === null
        ? "missing"
        : confidenceProvenance(confidence, "unverified");
    return {
      text: t(key, {
        value: value === null ? t("settings.car.ratio_unknown") : fmt(value, 2),
      }),
      tier: provenanceTier(provenance),
    };
  };
  if (gearbox.fuel_type === "EV") {
    // An EV's single reduction is its "final drive"; there is no top gear.
    return [
      part(
        "settings.car.gearbox_reduction",
        gearbox.final_drive_ratio,
        gearbox.final_drive_ratio_confidence,
      ),
    ];
  }
  return [
    part(
      "settings.car.gearbox_final_drive",
      gearbox.final_drive_ratio,
      gearbox.final_drive_ratio_confidence,
    ),
    part(
      "settings.car.gearbox_top_gear",
      gearbox.top_gear_ratio,
      gearbox.top_gear_ratio_confidence,
    ),
  ];
}

/** "2016–2022", or "2016" for a single model year; `null` when unknown. */
function modelYears(
  start: number | null | undefined,
  end: number | null | undefined,
): string | null {
  if (start == null || end == null) {
    const year = start ?? end;
    return year == null ? null : String(year);
  }
  return start === end ? String(start) : `${start}\u2013${end}`;
}

/**
 * "AWD · 2.0 diesel · 2016–2022". The years are left out when the name already
 * carries them: a variant split by model year is named "xDrive25d (2021–2022)".
 */
export function variantDetail(variant: CarLibraryVariant): string | null {
  const span = modelYears(
    variant.production_start_year,
    variant.production_end_year,
  );
  const years = span && !variant.name.endsWith(`(${span})`) ? span : null;
  return (
    [variant.drivetrain, variant.engine, years].filter(Boolean).join(" · ") ||
    null
  );
}

/**
 * The car's powertrain: the library's when it says, else the user's pick, else
 * the saved car's; `null` when nobody said.
 */
export function wizardFuelType(state: WizardState): FuelType {
  return (
    libraryFuelType(state) ?? state.fuelType ?? state.editing?.fuelType ?? null
  );
}

/** Whether the specs step asks for the powertrain: the library does not say. */
export function asksPowertrain(state: WizardState): boolean {
  return libraryFuelType(state) === null;
}

/** The powertrain all of the variant's gearboxes share, if any. */
function libraryFuelType(state: WizardState): FuelType {
  if (state.selectedGearbox) {
    return state.selectedGearbox.fuel_type;
  }
  const fuelTypes = new Set(
    resolveGearboxes(state.selectedModel, state.selectedVariant).map(
      (gearbox) => gearbox.fuel_type,
    ),
  );
  return fuelTypes.size === 1 ? [...fuelTypes][0] : null;
}

function confidenceOrNull(provenance: ReferenceProvenance) {
  return provenance === "missing" ? null : provenance;
}

export type CarRequest =
  | {
      ok: true;
      /** A `null` ratio is unknown: the car is saved without it. */
      aspects: Record<string, number | string | null>;
      status: CarOrderReferenceStatus;
      /** The library row's or the user's powertrain; `null` when unknown. */
      fuelType: FuelType;
    }
  | { ok: false; focus: ManualField };

/**
 * The car to create: library values the user kept carry their source
 * confidence; typed values are user-confirmed; empty ratios stay unknown.
 */
export function carRequest(
  state: WizardState,
  inputs: ManualInputs,
): CarRequest {
  const invalid = firstInvalidField(inputs);
  if (invalid) {
    return { ok: false, focus: invalid };
  }
  const refs = specProvenance(state, inputs);
  const keptTire = tireMatchesOption(state.selectedTire, inputs)
    ? state.selectedTire
    : null;
  const keptAspects = keptTire ? tireSetupAspectsFromOption(keptTire) : {};
  const tireAspects = Object.keys(keptAspects).length
    ? keptAspects
    : {
        rim_in: Number(inputs.rim),
        tire_aspect_pct: Number(inputs.tireAspect),
        tire_width_mm: Number(inputs.tireWidth),
      };
  const gearbox = state.selectedGearbox;
  const fromLibrary =
    keptTire !== null &&
    gearbox !== null &&
    sameRatio(inputs.finalDrive, ratioText(gearbox.final_drive_ratio)) &&
    sameRatio(inputs.topGear, ratioText(gearbox.top_gear_ratio));
  const status: CarOrderReferenceStatus = {
    tire_dimensions_confidence: confidenceOrNull(refs.tire),
    final_drive_ratio_confidence: confidenceOrNull(refs.finalDrive),
    current_gear_ratio_confidence: confidenceOrNull(refs.topGear),
    requires_manual_confirmation:
      estimateNoteKey(refs, wizardFuelType(state)) !== null,
    selection_source_status: fromLibrary ? "exact_row" : "manual_entry",
  };
  if (gearbox) {
    status.transmission_name = gearbox.name;
    status.transmission_confidence =
      gearbox.transmission_confidence ?? "unverified";
  }
  return {
    ok: true,
    aspects: {
      current_gear_ratio: positive(inputs.topGear),
      final_drive_ratio: positive(inputs.finalDrive),
      ...tireAspects,
    },
    status,
    fuelType: wizardFuelType(state),
  };
}

/** The aspects an edit changes; a `null` ratio clears it. */
export interface EditedAspects {
  tire_width_mm?: number;
  tire_aspect_pct?: number;
  rim_in?: number;
  final_drive_ratio?: number | null;
  current_gear_ratio?: number | null;
}

export type EditRequest =
  | {
      ok: true;
      aspects: EditedAspects;
      /** The powertrain the user set; `null` when it did not change. */
      fuelType: FuelType;
    }
  | { ok: false; focus: ManualField };

/**
 * The changes to save for an edited car: only the values that changed (a
 * cleared ratio is `null`). The server marks each changed value user-confirmed.
 */
export function editRequest(
  state: WizardState & { editing: EditTarget },
  inputs: ManualInputs,
): EditRequest {
  const { editing } = state;
  const invalid = firstInvalidField(inputs);
  if (invalid) {
    return { ok: false, focus: invalid };
  }
  return {
    ok: true,
    aspects: {
      ...(sameTire(inputs, editing.original)
        ? {}
        : {
            tire_width_mm: Number(inputs.tireWidth),
            tire_aspect_pct: Number(inputs.tireAspect),
            rim_in: Number(inputs.rim),
          }),
      ...(sameRatio(inputs.finalDrive, editing.original.finalDrive)
        ? {}
        : { final_drive_ratio: positive(inputs.finalDrive) }),
      ...(sameRatio(inputs.topGear, editing.original.topGear)
        ? {}
        : { current_gear_ratio: positive(inputs.topGear) }),
    },
    fuelType:
      state.fuelType && state.fuelType !== editing.fuelType
        ? state.fuelType
        : null,
  };
}

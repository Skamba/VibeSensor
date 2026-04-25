import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../api";
import type { WizardSummaryData } from "../views/car_wizard_view";
import { buildGearboxConfidenceHint } from "./car_confidence_summary";
import { formatCarLibraryTireOption } from "./cars_tire_setup";

export type WizardSpecBranch = "library" | "manual" | null;

export interface WizardState {
  step: number;
  brand: string;
  carType: string;
  model: string;
  selectedModel: CarLibraryModel | null;
  selectedVariant: CarLibraryVariant | null;
  selectedGearbox: CarLibraryGearbox | null;
  selectedTire: CarLibraryTireOption | null;
  specBranch: WizardSpecBranch;
}

export interface ManualTireValues {
  width: number;
  aspect: number;
  rim: number;
}

export interface ManualGearboxValues {
  finalDrive: number;
  topGear: number;
}

export const DEFAULT_CARS_WIZARD_MANUAL_INPUTS = {
  finalDrive: "3.08",
  rim: "18",
  tireAspect: "45",
  tireWidth: "225",
  topGear: "0.64",
} as const;

interface WizardTextDeps {
  fmt: (value: number, digits?: number) => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

interface WizardManualDeps extends WizardTextDeps {
  manualTire: ManualTireValues | null;
  manualGearbox: ManualGearboxValues | null;
}

export function createInitialWizardState(): WizardState {
  return {
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
}

export function resolveGearboxes(
  model: CarLibraryModel | null,
  variant: CarLibraryVariant | null,
): CarLibraryGearbox[] {
  if (variant?.gearboxes && variant.gearboxes.length > 0) return variant.gearboxes;
  return model?.gearboxes || [];
}

export function resolveTireOptions(
  model: CarLibraryModel | null,
  variant: CarLibraryVariant | null,
): CarLibraryTireOption[] {
  if (variant?.tire_options && variant.tire_options.length > 0) return variant.tire_options;
  return model?.tire_options || [];
}

export function buildWizardCarName(
  brand: string,
  model: string,
  variant: CarLibraryVariant | null,
): string {
  const variantSuffix = variant ? ` ${variant.name}` : "";
  if (brand) return `${brand} ${model || "Custom"}${variantSuffix}`;
  return (model || "Custom Car") + variantSuffix;
}

function readPositiveWizardNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function readWizardManualTireValues(
  step: number,
  values: { width: unknown; aspect: unknown; rim: unknown },
): ManualTireValues | null {
  if (step < 4) {
    return null;
  }
  const width = readPositiveWizardNumber(values.width);
  const aspect = readPositiveWizardNumber(values.aspect);
  const rim = readPositiveWizardNumber(values.rim);
  if (width == null || aspect == null || rim == null) {
    return null;
  }
  return { width, aspect, rim };
}

export function readWizardManualGearboxValues(
  step: number,
  values: { finalDrive: unknown; topGear: unknown },
): ManualGearboxValues | null {
  if (step < 4) {
    return null;
  }
  const finalDrive = readPositiveWizardNumber(values.finalDrive);
  const topGear = readPositiveWizardNumber(values.topGear);
  if (finalDrive == null || topGear == null) {
    return null;
  }
  return { finalDrive, topGear };
}

export function getResolvedWizardSpecBranch(state: WizardState): WizardSpecBranch {
  if (state.step !== 4) {
    return null;
  }
  const tireOptions = resolveTireOptions(state.selectedModel, state.selectedVariant);
  const gearboxes = resolveGearboxes(state.selectedModel, state.selectedVariant);
  if (!tireOptions.length || !gearboxes.length) {
    return "manual";
  }
  return state.specBranch;
}

function canFinishWithLibrarySpecs(state: WizardState): boolean {
  return Boolean(state.selectedTire && state.selectedGearbox);
}

function canFinishWithManualSpecs(
  manualTire: ManualTireValues | null,
  manualGearbox: ManualGearboxValues | null,
): boolean {
  return Boolean(manualTire && manualGearbox);
}

export function canFinishWizard(
  state: WizardState,
  manualTire: ManualTireValues | null,
  manualGearbox: ManualGearboxValues | null,
): boolean {
  const branch = getResolvedWizardSpecBranch(state);
  if (branch === "library") {
    return canFinishWithLibrarySpecs(state);
  }
  if (branch === "manual") {
    return canFinishWithManualSpecs(manualTire, manualGearbox);
  }
  return false;
}

function formatWizardRimSize(rim: number, fmt: WizardTextDeps["fmt"]): string {
  return fmt(rim, Number.isInteger(rim) ? 0 : 1);
}

function formatWizardTireLabel(
  tire: CarLibraryTireOption | null,
  fmt: WizardTextDeps["fmt"],
): string | null {
  if (!tire) {
    return null;
  }
  const size = formatCarLibraryTireOption(tire, fmt);
  if (!size) {
    return null;
  }
  return tire.name ? `${tire.name} · ${size}` : size;
}

function formatManualTireSummary(
  manualTire: ManualTireValues,
  deps: WizardTextDeps,
): string {
  const { fmt, t } = deps;
  return t("settings.car.wizard_summary_manual_tire", {
    width: fmt(manualTire.width, 0),
    aspect: fmt(manualTire.aspect, 0),
    rim: formatWizardRimSize(manualTire.rim, fmt),
  });
}

function formatManualGearboxSummary(
  manualGearbox: ManualGearboxValues,
  deps: WizardTextDeps,
): string {
  const { fmt, t } = deps;
  return t("settings.car.wizard_summary_manual_gearbox", {
    finalDrive: fmt(manualGearbox.finalDrive, 2),
    topGear: fmt(manualGearbox.topGear, 2),
  });
}

export function getWizardActionHint(
  state: WizardState,
  deps: WizardManualDeps,
): string {
  const { t, manualTire, manualGearbox } = deps;
  const branch = getResolvedWizardSpecBranch(state);
  if (branch === "library") {
    if (!canFinishWithLibrarySpecs(state)) {
      return t("settings.car.finish_choose_path");
    }
    return buildGearboxConfidenceHint(state.selectedGearbox, t)
      ?? t("settings.car.finish_library_ready");
  }
  if (branch === "manual") {
    return canFinishWithManualSpecs(manualTire, manualGearbox)
      ? t("settings.car.finish_manual_ready")
      : t("settings.car.finish_manual_missing");
  }
  return t("settings.car.finish_choose_path");
}

export function buildWizardSummaryData(
  state: WizardState,
  deps: WizardManualDeps,
): WizardSummaryData {
  const { fmt, manualGearbox, manualTire, t } = deps;
  const variantIsImplicit = Boolean(
    state.step >= 4
      && ((!state.selectedModel && state.model)
        || (state.selectedModel && (state.selectedModel.variants?.length ?? 0) === 0)),
  );
  const specBranch = getResolvedWizardSpecBranch(state);
  const selectedTireLabel = formatWizardTireLabel(state.selectedTire, fmt);
  return {
    currentStep: state.step,
    profileName: state.model
      ? buildWizardCarName(state.brand, state.model, state.selectedVariant)
      : null,
    brand: state.brand || null,
    carType: state.carType || null,
    model: state.model || null,
    variant: state.selectedVariant?.name
      || (variantIsImplicit ? t("settings.car.wizard_summary_not_needed") : null),
    tire: specBranch === "manual"
      ? (manualTire ? formatManualTireSummary(manualTire, deps) : selectedTireLabel)
      : selectedTireLabel,
    gearbox: specBranch === "manual"
      ? (manualGearbox ? formatManualGearboxSummary(manualGearbox, deps) : null)
      : (state.selectedGearbox?.name ?? null),
  };
}

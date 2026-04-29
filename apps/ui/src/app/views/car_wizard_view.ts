import type {
  CarLibraryGearbox,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../api";
import type {
  CarsFeatureRenderState,
} from "../features/cars_feature_workflow";
import type { CarsFeatureOptionsState } from "../features/cars_option_state";
import { DEFAULT_CARS_WIZARD_MANUAL_INPUTS } from "../features/cars_wizard_state";
import { formatCarLibraryTireOption } from "../features/cars_tire_setup";

type FormatNumber = (value: number, digits?: number) => string;
type Translate = (key: string, vars?: Record<string, unknown>) => string;

const WIZARD_STEP_LABEL_KEYS = [
  "settings.car.step_brand_short",
  "settings.car.step_type_short",
  "settings.car.step_model_short",
  "settings.car.step_variant_short",
  "settings.car.step_specs_short",
] as const;

type WizardOptionAttribute = "data-value" | "data-idx" | "data-tire-idx";
type WizardOptionLayout = "chips" | "list";

export interface WizardSummaryData {
  currentStep: number;
  profileName: string | null;
  brand: string | null;
  carType: string | null;
  model: string | null;
  variant: string | null;
  tire: string | null;
  gearbox: string | null;
}

export interface CarsWizardOptionItem {
  detailText: string | null;
  labelText: string;
  selected: boolean;
  value: string;
}

export interface CarsWizardOptionsRenderModel {
  attribute: WizardOptionAttribute;
  layout: WizardOptionLayout;
  messageText: string | null;
  options: readonly CarsWizardOptionItem[];
}

export interface CarsWizardSummaryRow {
  labelText: string;
  valueText: string;
}

export interface CarsWizardSummaryRenderModel {
  profileNameLabelText: string;
  profileNameValueText: string;
  rows: readonly CarsWizardSummaryRow[];
}

export interface CarsWizardRenderModel {
  actionHintText: string;
  backVisible: boolean;
  brandOptions: CarsWizardOptionsRenderModel;
  finishEnabled: boolean;
  finishVisible: boolean;
  gearboxOptions: CarsWizardOptionsRenderModel;
  isOpen: boolean;
  manualInputs: CarsFeatureRenderState["manualInputs"];
  modelOptions: CarsWizardOptionsRenderModel;
  progressText: string;
  specBranch: "library" | "manual" | "pending" | null;
  step: number;
  summary: CarsWizardSummaryRenderModel;
  tireOptions: CarsWizardOptionsRenderModel;
  typeOptions: CarsWizardOptionsRenderModel;
  variantOptions: CarsWizardOptionsRenderModel;
}

export function createClosedCarsWizardRenderModel(): CarsWizardRenderModel {
  return {
    actionHintText: "",
    backVisible: false,
    brandOptions: createOptionsModel("data-value"),
    finishEnabled: false,
    finishVisible: false,
    gearboxOptions: createOptionsModel("data-idx", "list"),
    isOpen: false,
    manualInputs: { ...DEFAULT_CARS_WIZARD_MANUAL_INPUTS },
    modelOptions: createOptionsModel("data-idx", "list"),
    progressText: "",
    specBranch: null,
    step: 0,
    summary: {
      profileNameLabelText: "",
      profileNameValueText: "",
      rows: [],
    },
    tireOptions: createOptionsModel("data-tire-idx"),
    typeOptions: createOptionsModel("data-value"),
    variantOptions: createOptionsModel("data-idx", "list"),
  };
}

function createOptionsModel(
  attribute: WizardOptionAttribute,
  layout: WizardOptionLayout = "chips",
): CarsWizardOptionsRenderModel {
  return {
    attribute,
    layout,
    messageText: null,
    options: [],
  };
}

function buildOptionsModel<TOption>(
  state: CarsFeatureOptionsState<TOption>,
  attribute: WizardOptionAttribute,
  buildItem: (option: TOption, index: number) => CarsWizardOptionItem,
  layout: WizardOptionLayout = "chips",
): CarsWizardOptionsRenderModel {
  if (state.status === "loading" || state.status === "error") {
    return {
      attribute,
      layout,
      messageText: state.message ?? "",
      options: [],
    };
  }
  if (state.status !== "ready") {
    return createOptionsModel(attribute, layout);
  }
  return {
    attribute,
    layout,
    messageText: null,
    options: state.options.map((option, index) => buildItem(option, index)),
  };
}

function buildVariantOptionsModel(
  variants: readonly CarLibraryVariant[],
): CarsWizardOptionsRenderModel {
  return {
    attribute: "data-idx",
    layout: "list",
    messageText: null,
    options: variants.map((variant, index) => ({
      detailText: [variant.drivetrain, variant.engine].filter(Boolean).join(" · ") || null,
      labelText: variant.name,
      selected: false,
      value: String(index),
    })),
  };
}

function buildTireOptionsModel(
  tireOptions: readonly CarLibraryTireOption[],
  selectedTire: CarLibraryTireOption | null,
  fmt: FormatNumber,
): CarsWizardOptionsRenderModel {
  return {
    attribute: "data-tire-idx",
    layout: "chips",
    messageText: null,
    options: tireOptions.map((tireOption, index) => ({
      detailText: formatCarLibraryTireOption(tireOption, fmt),
      labelText: tireOption.name,
      selected: tireOption === selectedTire,
      value: String(index),
    })),
  };
}

function buildGearboxOptionsModel(
  gearboxes: readonly CarLibraryGearbox[],
  selectedGearbox: CarLibraryGearbox | null,
  deps: { fmt: FormatNumber },
  noGearboxesMessage: string | null,
): CarsWizardOptionsRenderModel {
  if (noGearboxesMessage) {
    return {
      attribute: "data-idx",
      layout: "list",
      messageText: noGearboxesMessage,
      options: [],
    };
  }
  return {
    attribute: "data-idx",
    layout: "list",
    messageText: null,
    options: gearboxes.map((gearbox, index) => ({
      detailText: `FD: ${deps.fmt(gearbox.final_drive_ratio, 2)} · Top Gear: ${deps.fmt(gearbox.top_gear_ratio, 2)}`,
      labelText: gearbox.name,
      selected: gearbox === selectedGearbox,
      value: String(index),
    })),
  };
}

function buildSummaryRows(
  summary: WizardSummaryData,
  t: Translate,
): CarsWizardSummaryRow[] {
  const pending = t("settings.car.wizard_summary_pending");
  const rows = [
    { labelText: t("settings.car.wizard_summary_brand"), valueText: summary.brand, visibleFromStep: 1 },
    { labelText: t("settings.car.wizard_summary_type"), valueText: summary.carType, visibleFromStep: 2 },
    { labelText: t("settings.car.wizard_summary_model"), valueText: summary.model, visibleFromStep: 3 },
    { labelText: t("settings.car.wizard_summary_variant"), valueText: summary.variant, visibleFromStep: 4 },
    { labelText: t("settings.car.wizard_summary_tire"), valueText: summary.tire, visibleFromStep: 4 },
    { labelText: t("settings.car.wizard_summary_gearbox"), valueText: summary.gearbox, visibleFromStep: 4 },
  ];
  return rows
    .filter((row) => row.valueText || summary.currentStep >= row.visibleFromStep)
    .map((row) => ({
      labelText: row.labelText,
      valueText: row.valueText ?? pending,
    }));
}

export function buildCarsWizardRenderModel(
  state: CarsFeatureRenderState,
  deps: { fmt: FormatNumber; t: Translate },
): CarsWizardRenderModel {
  const { fmt, t } = deps;
  const pending = t("settings.car.wizard_summary_pending");
  return {
    actionHintText: state.actionHint,
    backVisible: state.step > 0,
    brandOptions: buildOptionsModel(
      state.brandOptions,
      "data-value",
      (brand) => ({
        detailText: null,
        labelText: brand,
        selected: false,
        value: brand,
      }),
    ),
    finishEnabled: state.step === 4 && state.canFinish,
    finishVisible: state.step === 4,
    gearboxOptions: buildGearboxOptionsModel(
      state.gearboxOptions,
      state.selectedGearbox,
      { fmt },
      state.noGearboxesMessage,
    ),
    isOpen: state.isOpen,
    manualInputs: { ...state.manualInputs },
    modelOptions: buildOptionsModel(
      state.modelOptions,
      "data-idx",
      (model, index) => ({
        detailText: `${model.tire_width_mm}/${model.tire_aspect_pct}R${model.rim_in}`,
        labelText: model.model,
        selected: false,
        value: String(index),
      }),
      "list",
    ),
    progressText: t("settings.car.wizard_progress", {
      current: state.step + 1,
      step: t(WIZARD_STEP_LABEL_KEYS[state.step] ?? WIZARD_STEP_LABEL_KEYS[0]),
      total: WIZARD_STEP_LABEL_KEYS.length,
    }),
    specBranch: state.step === 4 ? state.resolvedSpecBranch ?? "pending" : null,
    step: state.step,
    summary: {
      profileNameLabelText: t("settings.car.wizard_summary_name"),
      profileNameValueText: state.summaryData.profileName ?? pending,
      rows: buildSummaryRows(state.summaryData, t),
    },
    tireOptions: buildTireOptionsModel(state.tireOptions, state.selectedTire, fmt),
    typeOptions: buildOptionsModel(
      state.typeOptions,
      "data-value",
      (carType) => ({
        detailText: null,
        labelText: carType,
        selected: false,
        value: carType,
      }),
    ),
    variantOptions: buildVariantOptionsModel(state.variantOptions),
  };
}

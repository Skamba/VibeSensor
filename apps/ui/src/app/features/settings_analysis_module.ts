import type {
  AnalysisSettingsPayload,
  AnalysisSettingsRequest,
} from "../../api/types";
import { getAnalysisSettings, setAnalysisSettings } from "../../api";
import type { FeatureServices } from "../feature_deps_base";
import {
  defaultVehicleSettings,
  mergeAnalysisTuningSettings,
  type SettingsState,
} from "../ui_app_state";
import { batch, computed, signal } from "../ui_signals";
import type {
  AnalysisPanelFieldKey,
  AnalysisPanelRenderModel,
  AnalysisPanelView,
  SettingsAnalysisGuidanceRenderModel,
} from "../views/analysis_panel";
import type { SettingsFeedbackMessage } from "../views/settings_feedback";

export interface SettingsAnalysisModuleDeps {
  panel: AnalysisPanelView;
  settings: SettingsState;
  services: FeatureServices;
  refreshSpectrumDecorations: () => void;
  hasValidActiveCar: () => boolean;
  onMissingActiveCar: () => void;
  onSaveError: (error: unknown) => void;
}

export interface SettingsAnalysisModule {
  bindHandlers(): void;
  syncSettingsInputs(): void;
  loadAnalysisSettingsFromServer(): Promise<void>;
  saveAnalysisFromInputs(): void;
}

type EditableAnalysisDrafts = Record<AnalysisPanelFieldKey, string>;
type UnitSuffix = "%" | " Hz";

interface AnalysisFieldConfig {
  key: AnalysisPanelFieldKey;
  labelKey: string;
  unit: UnitSuffix;
  hardMin: number;
  hardMax: number;
  guidedMin: number;
  guidedMax: number;
  defaultValue: number;
}

interface AnalysisFieldState {
  config: AnalysisFieldConfig;
  rawValue: string;
  numericValue: number;
}

const EDITABLE_ANALYSIS_KEYS = [
  "wheel_bandwidth_pct",
  "driveshaft_bandwidth_pct",
  "engine_bandwidth_pct",
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
  "min_abs_band_hz",
  "max_band_half_width_pct",
] as const satisfies readonly AnalysisPanelFieldKey[];

const ANALYSIS_FIELD_CONFIGS: Record<AnalysisPanelFieldKey, AnalysisFieldConfig> = {
  wheel_bandwidth_pct: {
    key: "wheel_bandwidth_pct",
    labelKey: "settings.wheel_bandwidth",
    unit: "%",
    hardMin: 0.1,
    hardMax: 100,
    guidedMin: 2,
    guidedMax: 12,
    defaultValue: defaultVehicleSettings.wheel_bandwidth_pct,
  },
  driveshaft_bandwidth_pct: {
    key: "driveshaft_bandwidth_pct",
    labelKey: "settings.driveshaft_bandwidth",
    unit: "%",
    hardMin: 0.1,
    hardMax: 100,
    guidedMin: 2,
    guidedMax: 10,
    defaultValue: defaultVehicleSettings.driveshaft_bandwidth_pct,
  },
  engine_bandwidth_pct: {
    key: "engine_bandwidth_pct",
    labelKey: "settings.engine_bandwidth",
    unit: "%",
    hardMin: 0.1,
    hardMax: 100,
    guidedMin: 2,
    guidedMax: 12,
    defaultValue: defaultVehicleSettings.engine_bandwidth_pct,
  },
  speed_uncertainty_pct: {
    key: "speed_uncertainty_pct",
    labelKey: "settings.speed_uncertainty",
    unit: "%",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 5,
    defaultValue: defaultVehicleSettings.speed_uncertainty_pct,
  },
  tire_diameter_uncertainty_pct: {
    key: "tire_diameter_uncertainty_pct",
    labelKey: "settings.tire_diameter_uncertainty",
    unit: "%",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 5,
    defaultValue: defaultVehicleSettings.tire_diameter_uncertainty_pct,
  },
  final_drive_uncertainty_pct: {
    key: "final_drive_uncertainty_pct",
    labelKey: "settings.final_drive_uncertainty",
    unit: "%",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 2,
    defaultValue: defaultVehicleSettings.final_drive_uncertainty_pct,
  },
  gear_uncertainty_pct: {
    key: "gear_uncertainty_pct",
    labelKey: "settings.gear_slip_uncertainty",
    unit: "%",
    hardMin: 0,
    hardMax: 100,
    guidedMin: 0,
    guidedMax: 4,
    defaultValue: defaultVehicleSettings.gear_uncertainty_pct,
  },
  min_abs_band_hz: {
    key: "min_abs_band_hz",
    labelKey: "settings.min_half_width",
    unit: " Hz",
    hardMin: 0,
    hardMax: 500,
    guidedMin: 0,
    guidedMax: 2,
    defaultValue: defaultVehicleSettings.min_abs_band_hz,
  },
  max_band_half_width_pct: {
    key: "max_band_half_width_pct",
    labelKey: "settings.max_half_width",
    unit: "%",
    hardMin: 0.1,
    hardMax: 100,
    guidedMin: 1,
    guidedMax: 12,
    defaultValue: defaultVehicleSettings.max_band_half_width_pct,
  },
};

function analysisFieldConfig(key: AnalysisPanelFieldKey): AnalysisFieldConfig {
  return ANALYSIS_FIELD_CONFIGS[key];
}

function buildDraftValues(settings: SettingsState): EditableAnalysisDrafts {
  const vehicleSettings = settings.analysis.vehicleSettings.value;
  return {
    wheel_bandwidth_pct: formatSettingValue(vehicleSettings.wheel_bandwidth_pct),
    driveshaft_bandwidth_pct: formatSettingValue(
      vehicleSettings.driveshaft_bandwidth_pct,
    ),
    engine_bandwidth_pct: formatSettingValue(vehicleSettings.engine_bandwidth_pct),
    speed_uncertainty_pct: formatSettingValue(vehicleSettings.speed_uncertainty_pct),
    tire_diameter_uncertainty_pct: formatSettingValue(
      vehicleSettings.tire_diameter_uncertainty_pct,
    ),
    final_drive_uncertainty_pct: formatSettingValue(
      vehicleSettings.final_drive_uncertainty_pct,
    ),
    gear_uncertainty_pct: formatSettingValue(vehicleSettings.gear_uncertainty_pct),
    min_abs_band_hz: formatSettingValue(vehicleSettings.min_abs_band_hz),
    max_band_half_width_pct: formatSettingValue(
      vehicleSettings.max_band_half_width_pct,
    ),
  };
}

function formatSettingValue(value: number): string {
  return Number.isInteger(value)
    ? String(value)
    : String(Number(value.toFixed(1)));
}

export function createSettingsAnalysisModule(
  ctx: SettingsAnalysisModuleDeps,
): SettingsAnalysisModule {
  const { panel, settings, services } = ctx;
  const { t } = services;
  const draftValues = signal(buildDraftValues(settings));
  const saveFeedback = signal<SettingsFeedbackMessage | null>(null);
  const fieldErrorMessages = signal<Partial<Record<AnalysisPanelFieldKey, string>>>({});

  function formatRange(min: number, max: number, unit: UnitSuffix): string {
    return t("settings.analysis.range_value", {
      min: formatSettingValue(min),
      max: formatSettingValue(max),
      unit,
    });
  }

  function buildPanelModel(): AnalysisPanelRenderModel {
    return {
      fields: {
        wheel_bandwidth_pct: buildFieldRenderModel("wheel_bandwidth_pct"),
        driveshaft_bandwidth_pct: buildFieldRenderModel("driveshaft_bandwidth_pct"),
        engine_bandwidth_pct: buildFieldRenderModel("engine_bandwidth_pct"),
        speed_uncertainty_pct: buildFieldRenderModel("speed_uncertainty_pct"),
        tire_diameter_uncertainty_pct: buildFieldRenderModel(
          "tire_diameter_uncertainty_pct",
        ),
        final_drive_uncertainty_pct: buildFieldRenderModel(
          "final_drive_uncertainty_pct",
        ),
        gear_uncertainty_pct: buildFieldRenderModel("gear_uncertainty_pct"),
        min_abs_band_hz: buildFieldRenderModel("min_abs_band_hz"),
        max_band_half_width_pct: buildFieldRenderModel("max_band_half_width_pct"),
      },
      saveFeedback: saveFeedback.value,
    };
  }

  function buildFieldRenderModel(fieldKey: AnalysisPanelFieldKey) {
    const field = analysisFieldConfig(fieldKey);
    const errorMessage = fieldErrorMessages.value[field.key];
    const guidance: SettingsAnalysisGuidanceRenderModel = {
      error: errorMessage
        ? {
            body: errorMessage,
            compact: true,
            tone: "error",
          }
        : null,
      lines: [
        {
          label: t("settings.analysis.recommended_range_label"),
          value: formatRange(field.guidedMin, field.guidedMax, field.unit),
        },
        {
          label: t("settings.analysis.default_label"),
          value: `${formatSettingValue(field.defaultValue)}${field.unit}`,
        },
      ],
    };
    return {
      guidance,
      invalid: errorMessage !== undefined,
      value: draftValues.value[field.key],
    };
  }
  const panelModel = computed(() => buildPanelModel());
  panel.model.value = panelModel;

  function clearFieldValidationState(): void {
    fieldErrorMessages.value = {};
  }

  function openAnalysisGuidance(): void {
    panel.openGuidance();
  }

  function markFieldInvalid(field: AnalysisFieldConfig, message: string): void {
    fieldErrorMessages.value = {
      ...fieldErrorMessages.value,
      [field.key]: message,
    };
    panel.focusField(field.key);
    openAnalysisGuidance();
  }

  function collectFieldStates(): AnalysisFieldState[] {
    return EDITABLE_ANALYSIS_KEYS.map((fieldKey) => {
      const config = analysisFieldConfig(fieldKey);
      const rawValue = draftValues.value[fieldKey].trim();
      return {
        config,
        rawValue,
        numericValue: Number(rawValue),
      };
    });
  }

  function buildEditableAnalysisPayload(
    states: readonly AnalysisFieldState[],
  ): AnalysisSettingsRequest {
    return states.reduce<AnalysisSettingsRequest>((payload, field) => {
      payload[field.config.key] = field.numericValue;
      return payload;
    }, {});
  }

  async function resetAnalysisToDefaults(): Promise<void> {
    if (!ctx.hasValidActiveCar()) {
      ctx.onMissingActiveCar();
      return;
    }
    const ok = await ctx.services.requestConfirmation(
      t("settings.analysis.reset_confirm"),
    );
    if (!ok) {
      return;
    }
    clearFieldValidationState();
    saveFeedback.value = null;
    void syncAnalysisSettingsToServer({
      wheel_bandwidth_pct: defaultVehicleSettings.wheel_bandwidth_pct,
      driveshaft_bandwidth_pct: defaultVehicleSettings.driveshaft_bandwidth_pct,
      engine_bandwidth_pct: defaultVehicleSettings.engine_bandwidth_pct,
      speed_uncertainty_pct: defaultVehicleSettings.speed_uncertainty_pct,
      tire_diameter_uncertainty_pct:
        defaultVehicleSettings.tire_diameter_uncertainty_pct,
      final_drive_uncertainty_pct:
        defaultVehicleSettings.final_drive_uncertainty_pct,
      gear_uncertainty_pct: defaultVehicleSettings.gear_uncertainty_pct,
      min_abs_band_hz: defaultVehicleSettings.min_abs_band_hz,
      max_band_half_width_pct: defaultVehicleSettings.max_band_half_width_pct,
    });
  }

  function syncSettingsInputs(): void {
    draftValues.value = buildDraftValues(settings);
    clearFieldValidationState();
    saveFeedback.value = null;
  }

  function applyAnalysisSettingsPayload(
    serverSettings: AnalysisSettingsPayload,
  ): void {
    settings.analysis.vehicleSettings.value = mergeAnalysisTuningSettings(
      settings.analysis.vehicleSettings.value,
      serverSettings,
    );
    syncSettingsInputs();
    ctx.refreshSpectrumDecorations();
  }

  async function syncAnalysisSettingsToServer(
    payload: AnalysisSettingsRequest,
  ): Promise<void> {
    try {
      const saved = await setAnalysisSettings(payload);
      applyAnalysisSettingsPayload(saved);
    } catch (error) {
      openAnalysisGuidance();
      saveFeedback.value = {
        tone: "error",
        title: t("settings.analysis.save_failed_title"),
        body:
          error instanceof Error ? error.message : t("settings.save_failed"),
        detail: t("settings.analysis.save_failed_detail"),
      };
      ctx.onSaveError(error);
    }
  }

  async function loadAnalysisSettingsFromServer(): Promise<void> {
    const serverSettings = await getAnalysisSettings();
    if (serverSettings) {
      applyAnalysisSettingsPayload(serverSettings);
    }
  }

  async function saveAnalysisFromInputsInternal(): Promise<void> {
    if (!ctx.hasValidActiveCar()) {
      ctx.onMissingActiveCar();
      return;
    }
    clearFieldValidationState();
    saveFeedback.value = null;
    const fieldStates = collectFieldStates();
    const missingField = fieldStates.find(
      (field) =>
        field.rawValue === "" ||
        Number.isNaN(field.numericValue) ||
        !Number.isFinite(field.numericValue),
    );
    if (missingField) {
      markFieldInvalid(
        missingField.config,
        t("settings.analysis.invalid_number", {
          field: t(missingField.config.labelKey),
        }),
      );
      return;
    }
    const outOfBoundsField = fieldStates.find(
      (field) =>
        field.numericValue < field.config.hardMin ||
        field.numericValue > field.config.hardMax,
    );
    if (outOfBoundsField) {
      markFieldInvalid(
        outOfBoundsField.config,
        t("settings.analysis.invalid_value", {
          field: t(outOfBoundsField.config.labelKey),
          min: formatSettingValue(outOfBoundsField.config.hardMin),
          max: formatSettingValue(outOfBoundsField.config.hardMax),
          value: formatSettingValue(outOfBoundsField.numericValue),
          unit: outOfBoundsField.config.unit,
        }),
      );
      return;
    }
    const riskyFields = fieldStates.filter(
      (field) =>
        field.numericValue < field.config.guidedMin ||
        field.numericValue > field.config.guidedMax,
    );
    if (riskyFields.length > 0) {
      const intro = t("settings.analysis.risky_confirm_intro");
      const details = riskyFields.map((field) =>
        t("settings.analysis.risky_confirm_line", {
          field: t(field.config.labelKey),
          value: formatSettingValue(field.numericValue),
          min: formatSettingValue(field.config.guidedMin),
          max: formatSettingValue(field.config.guidedMax),
          defaultValue: formatSettingValue(field.config.defaultValue),
          unit: field.config.unit,
        }),
      );
      const ok = await ctx.services.requestConfirmation(
        [
          intro,
          ...details,
          "",
          t("settings.analysis.risky_confirm_outro"),
        ].join("\n"),
      );
      if (!ok) {
        return;
      }
    }
    const payload = buildEditableAnalysisPayload(fieldStates);
    void syncAnalysisSettingsToServer(payload);
  }

  function saveAnalysisFromInputs(): void {
    void saveAnalysisFromInputsInternal();
  }

  function handleFieldInput(
    action: { field: AnalysisPanelFieldKey; value: string },
  ): void {
    batch(() => {
      draftValues.value = {
        ...draftValues.value,
        [action.field]: action.value,
      };
      const nextErrors = { ...fieldErrorMessages.value };
      delete nextErrors[action.field];
      fieldErrorMessages.value = nextErrors;
      saveFeedback.value = null;
    });
  }

  function bindHandlers(): void {
    panel.actions.value = {
      onFieldInput: handleFieldInput,
      onReset: () => {
        void resetAnalysisToDefaults();
      },
      onSave: saveAnalysisFromInputs,
    };
  }

  return {
    bindHandlers,
    syncSettingsInputs,
    loadAnalysisSettingsFromServer,
    saveAnalysisFromInputs,
  };
}

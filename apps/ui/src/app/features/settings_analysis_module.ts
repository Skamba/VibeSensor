import type { AnalysisSettingsRequest, AnalysisSettingsPayload } from "../../api/types";
import { getAnalysisSettings, setAnalysisSettings } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import { defaultVehicleSettings, type SettingsState } from "../ui_app_state";

export const ANALYSIS_SETTING_KEYS = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
  "final_drive_ratio",
  "current_gear_ratio",
  "wheel_bandwidth_pct",
  "driveshaft_bandwidth_pct",
  "engine_bandwidth_pct",
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
  "min_abs_band_hz",
  "max_band_half_width_pct",
  "tire_deflection_factor",
] as const satisfies readonly (keyof AnalysisSettingsPayload)[];

export interface SettingsAnalysisModuleDeps extends FeatureDepsBase {
  settings: SettingsState;
  renderSpectrum: () => void;
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

export function createSettingsAnalysisModule(ctx: SettingsAnalysisModuleDeps): SettingsAnalysisModule {
  const { settings, els, t } = ctx;
  type EditableAnalysisKey =
    | "wheel_bandwidth_pct"
    | "driveshaft_bandwidth_pct"
    | "engine_bandwidth_pct"
    | "speed_uncertainty_pct"
    | "tire_diameter_uncertainty_pct"
    | "final_drive_uncertainty_pct"
    | "gear_uncertainty_pct"
    | "min_abs_band_hz"
    | "max_band_half_width_pct";
  type UnitSuffix = "%" | " Hz";
  interface AnalysisFieldConfig {
    key: EditableAnalysisKey;
    labelKey: string;
    unit: UnitSuffix;
    hardMin: number;
    hardMax: number;
    guidedMin: number;
    guidedMax: number;
    defaultValue: number;
    guidanceId: string;
    input: () => HTMLInputElement | null;
  }
  const analysisFields: readonly AnalysisFieldConfig[] = [
    {
      key: "wheel_bandwidth_pct",
      labelKey: "settings.wheel_bandwidth",
      unit: "%",
      hardMin: 0.1,
      hardMax: 100,
      guidedMin: 2,
      guidedMax: 12,
      defaultValue: defaultVehicleSettings.wheel_bandwidth_pct,
      guidanceId: "wheelBandwidthGuidance",
      input: () => els.wheelBandwidthInput,
    },
    {
      key: "driveshaft_bandwidth_pct",
      labelKey: "settings.driveshaft_bandwidth",
      unit: "%",
      hardMin: 0.1,
      hardMax: 100,
      guidedMin: 2,
      guidedMax: 10,
      defaultValue: defaultVehicleSettings.driveshaft_bandwidth_pct,
      guidanceId: "driveshaftBandwidthGuidance",
      input: () => els.driveshaftBandwidthInput,
    },
    {
      key: "engine_bandwidth_pct",
      labelKey: "settings.engine_bandwidth",
      unit: "%",
      hardMin: 0.1,
      hardMax: 100,
      guidedMin: 2,
      guidedMax: 12,
      defaultValue: defaultVehicleSettings.engine_bandwidth_pct,
      guidanceId: "engineBandwidthGuidance",
      input: () => els.engineBandwidthInput,
    },
    {
      key: "speed_uncertainty_pct",
      labelKey: "settings.speed_uncertainty",
      unit: "%",
      hardMin: 0,
      hardMax: 100,
      guidedMin: 0,
      guidedMax: 5,
      defaultValue: defaultVehicleSettings.speed_uncertainty_pct,
      guidanceId: "speedUncertaintyGuidance",
      input: () => els.speedUncertaintyInput,
    },
    {
      key: "tire_diameter_uncertainty_pct",
      labelKey: "settings.tire_diameter_uncertainty",
      unit: "%",
      hardMin: 0,
      hardMax: 100,
      guidedMin: 0,
      guidedMax: 5,
      defaultValue: defaultVehicleSettings.tire_diameter_uncertainty_pct,
      guidanceId: "tireDiameterUncertaintyGuidance",
      input: () => els.tireDiameterUncertaintyInput,
    },
    {
      key: "final_drive_uncertainty_pct",
      labelKey: "settings.final_drive_uncertainty",
      unit: "%",
      hardMin: 0,
      hardMax: 100,
      guidedMin: 0,
      guidedMax: 2,
      defaultValue: defaultVehicleSettings.final_drive_uncertainty_pct,
      guidanceId: "finalDriveUncertaintyGuidance",
      input: () => els.finalDriveUncertaintyInput,
    },
    {
      key: "gear_uncertainty_pct",
      labelKey: "settings.gear_slip_uncertainty",
      unit: "%",
      hardMin: 0,
      hardMax: 100,
      guidedMin: 0,
      guidedMax: 4,
      defaultValue: defaultVehicleSettings.gear_uncertainty_pct,
      guidanceId: "gearUncertaintyGuidance",
      input: () => els.gearUncertaintyInput,
    },
    {
      key: "min_abs_band_hz",
      labelKey: "settings.min_half_width",
      unit: " Hz",
      hardMin: 0,
      hardMax: 500,
      guidedMin: 0,
      guidedMax: 2,
      defaultValue: defaultVehicleSettings.min_abs_band_hz,
      guidanceId: "minAbsBandHzGuidance",
      input: () => els.minAbsBandHzInput,
    },
    {
      key: "max_band_half_width_pct",
      labelKey: "settings.max_half_width",
      unit: "%",
      hardMin: 0.1,
      hardMax: 100,
      guidedMin: 1,
      guidedMax: 12,
      defaultValue: defaultVehicleSettings.max_band_half_width_pct,
      guidanceId: "maxBandHalfWidthGuidance",
      input: () => els.maxBandHalfWidthInput,
    },
  ];

  interface AnalysisFieldState {
    config: AnalysisFieldConfig;
    rawValue: string;
    numericValue: number;
  }

  function formatSettingValue(value: number): string {
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(1)));
  }

  function clearFieldValidationState(): void {
    for (const field of analysisFields) {
      field.input()?.removeAttribute("aria-invalid");
    }
  }

  function markFieldInvalid(field: AnalysisFieldConfig): void {
    field.input()?.setAttribute("aria-invalid", "true");
    field.input()?.focus();
  }

  function renderFieldGuidance(): void {
    for (const field of analysisFields) {
      const help = document.getElementById(field.guidanceId);
      if (!help) {
        continue;
      }
      help.textContent = t("settings.analysis.field_guidance", {
        defaultValue: formatSettingValue(field.defaultValue),
        min: formatSettingValue(field.guidedMin),
        max: formatSettingValue(field.guidedMax),
        unit: field.unit,
      });
    }
  }

  function applyInputConstraints(): void {
    for (const field of analysisFields) {
      const input = field.input();
      if (!input) {
        continue;
      }
      input.min = String(field.hardMin);
      input.max = String(field.hardMax);
      input.step = "0.1";
    }
  }

  function collectFieldStates(): AnalysisFieldState[] {
    return analysisFields.map((config) => {
      const rawValue = config.input()?.value.trim() ?? "";
      return {
        config,
        rawValue,
        numericValue: Number(rawValue),
      };
    });
  }

  function buildEditableAnalysisPayload(states: readonly AnalysisFieldState[]): AnalysisSettingsRequest {
    return states.reduce<AnalysisSettingsRequest>((payload, field) => {
      payload[field.config.key] = field.numericValue;
      return payload;
    }, {});
  }

  function resetAnalysisToDefaults(): void {
    if (!ctx.hasValidActiveCar()) {
      ctx.onMissingActiveCar();
      return;
    }
    const ok = window.confirm(t("settings.analysis.reset_confirm"));
    if (!ok) {
      return;
    }
    clearFieldValidationState();
    void syncAnalysisSettingsToServer({
      wheel_bandwidth_pct: defaultVehicleSettings.wheel_bandwidth_pct,
      driveshaft_bandwidth_pct: defaultVehicleSettings.driveshaft_bandwidth_pct,
      engine_bandwidth_pct: defaultVehicleSettings.engine_bandwidth_pct,
      speed_uncertainty_pct: defaultVehicleSettings.speed_uncertainty_pct,
      tire_diameter_uncertainty_pct: defaultVehicleSettings.tire_diameter_uncertainty_pct,
      final_drive_uncertainty_pct: defaultVehicleSettings.final_drive_uncertainty_pct,
      gear_uncertainty_pct: defaultVehicleSettings.gear_uncertainty_pct,
      min_abs_band_hz: defaultVehicleSettings.min_abs_band_hz,
      max_band_half_width_pct: defaultVehicleSettings.max_band_half_width_pct,
    });
  }

  function syncNumericInputValue(input: HTMLInputElement | null, value: number): void {
    if (input) input.value = String(value);
  }

  function syncSettingsInputs(): void {
    applyInputConstraints();
    clearFieldValidationState();
    renderFieldGuidance();
    syncNumericInputValue(els.wheelBandwidthInput, settings.vehicleSettings.wheel_bandwidth_pct);
    syncNumericInputValue(els.driveshaftBandwidthInput, settings.vehicleSettings.driveshaft_bandwidth_pct);
    syncNumericInputValue(els.engineBandwidthInput, settings.vehicleSettings.engine_bandwidth_pct);
    syncNumericInputValue(els.speedUncertaintyInput, settings.vehicleSettings.speed_uncertainty_pct);
    syncNumericInputValue(els.tireDiameterUncertaintyInput, settings.vehicleSettings.tire_diameter_uncertainty_pct);
    syncNumericInputValue(els.finalDriveUncertaintyInput, settings.vehicleSettings.final_drive_uncertainty_pct);
    syncNumericInputValue(els.gearUncertaintyInput, settings.vehicleSettings.gear_uncertainty_pct);
    syncNumericInputValue(els.minAbsBandHzInput, settings.vehicleSettings.min_abs_band_hz);
    syncNumericInputValue(els.maxBandHalfWidthInput, settings.vehicleSettings.max_band_half_width_pct);
  }

  function applyAnalysisSettingsPayload(serverSettings: AnalysisSettingsPayload): void {
    for (const key of ANALYSIS_SETTING_KEYS) {
      const value = serverSettings[key];
      if (typeof value === "number") settings.vehicleSettings[key] = value;
    }
    syncSettingsInputs();
    ctx.renderSpectrum();
  }

  async function syncAnalysisSettingsToServer(payload: AnalysisSettingsRequest): Promise<void> {
    try {
      const saved = await setAnalysisSettings(payload);
      applyAnalysisSettingsPayload(saved);
    } catch (error) {
      syncSettingsInputs();
      ctx.onSaveError(error);
    }
  }

  async function loadAnalysisSettingsFromServer(): Promise<void> {
    try {
      const serverSettings = await getAnalysisSettings();
      if (serverSettings) {
        applyAnalysisSettingsPayload(serverSettings);
      }
    } catch (_err) { /* ignore */ }
  }

  function saveAnalysisFromInputs(): void {
    if (!ctx.hasValidActiveCar()) {
      ctx.onMissingActiveCar();
      return;
    }
    clearFieldValidationState();
    const fieldStates = collectFieldStates();
    const missingField = fieldStates.find((field) => field.rawValue === "" || Number.isNaN(field.numericValue) || !Number.isFinite(field.numericValue));
    if (missingField) {
      markFieldInvalid(missingField.config);
      ctx.showError(t("settings.analysis.invalid_number", { field: t(missingField.config.labelKey) }));
      return;
    }
    const outOfBoundsField = fieldStates.find((field) => field.numericValue < field.config.hardMin || field.numericValue > field.config.hardMax);
    if (outOfBoundsField) {
      markFieldInvalid(outOfBoundsField.config);
      ctx.showError(t("settings.analysis.invalid_value", {
        field: t(outOfBoundsField.config.labelKey),
        min: formatSettingValue(outOfBoundsField.config.hardMin),
        max: formatSettingValue(outOfBoundsField.config.hardMax),
        value: formatSettingValue(outOfBoundsField.numericValue),
        unit: outOfBoundsField.config.unit,
      }));
      return;
    }
    const riskyFields = fieldStates.filter((field) => field.numericValue < field.config.guidedMin || field.numericValue > field.config.guidedMax);
    if (riskyFields.length > 0) {
      const intro = t("settings.analysis.risky_confirm_intro");
      const details = riskyFields.map((field) => t("settings.analysis.risky_confirm_line", {
        field: t(field.config.labelKey),
        value: formatSettingValue(field.numericValue),
        min: formatSettingValue(field.config.guidedMin),
        max: formatSettingValue(field.config.guidedMax),
        defaultValue: formatSettingValue(field.config.defaultValue),
        unit: field.config.unit,
      }));
      const ok = window.confirm([intro, ...details, "", t("settings.analysis.risky_confirm_outro")].join("\n"));
      if (!ok) {
        return;
      }
    }
    const payload = buildEditableAnalysisPayload(fieldStates);
    for (const key of ANALYSIS_SETTING_KEYS) {
      if (!(key in payload)) {
        payload[key] = settings.vehicleSettings[key];
      }
    }
    void syncAnalysisSettingsToServer(payload);
  }

  function bindHandlers(): void {
    applyInputConstraints();
    renderFieldGuidance();
    els.saveAnalysisBtn?.addEventListener("click", saveAnalysisFromInputs);
    els.resetAnalysisBtn?.addEventListener("click", resetAnalysisToDefaults);
    for (const field of analysisFields) {
      field.input()?.addEventListener("input", () => {
        field.input()?.removeAttribute("aria-invalid");
      });
    }
  }

  return {
    bindHandlers,
    syncSettingsInputs,
    loadAnalysisSettingsFromServer,
    saveAnalysisFromInputs,
  };
}

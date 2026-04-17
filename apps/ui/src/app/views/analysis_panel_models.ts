import type { SettingsFeedbackMessage } from "./settings_feedback";

export interface SettingsAnalysisGuidanceLine {
  label: string;
  value: string;
}

export interface SettingsAnalysisGuidanceRenderModel {
  error: SettingsFeedbackMessage | null;
  lines: readonly SettingsAnalysisGuidanceLine[];
}

export type AnalysisPanelFieldKey =
  | "wheel_bandwidth_pct"
  | "driveshaft_bandwidth_pct"
  | "engine_bandwidth_pct"
  | "speed_uncertainty_pct"
  | "tire_diameter_uncertainty_pct"
  | "final_drive_uncertainty_pct"
  | "gear_uncertainty_pct"
  | "min_abs_band_hz"
  | "max_band_half_width_pct";

export interface AnalysisPanelFieldRenderModel {
  guidance: SettingsAnalysisGuidanceRenderModel;
  invalid: boolean;
  value: string;
}

export interface AnalysisPanelRenderModel {
  fields: Record<AnalysisPanelFieldKey, AnalysisPanelFieldRenderModel>;
  saveFeedback: SettingsFeedbackMessage | null;
}

export interface AnalysisPanelCarAvailability {
  hasActiveCar: boolean;
  isLoading: boolean;
}

export interface AnalysisPanelActionHandlers {
  onFieldInput(action: { field: AnalysisPanelFieldKey; value: string }): void;
  onReset(): void;
  onSave(): void;
}

export type AnalysisFieldSpec = {
  fallbackLabel: string;
  guidanceId: string;
  inputId: string;
  key: AnalysisPanelFieldKey;
  labelKey: string;
  step: string;
};

export const ORDER_BAND_FIELDS: readonly AnalysisFieldSpec[] = [
  {
    fallbackLabel: "Wheel Bandwidth (%)",
    guidanceId: "wheelBandwidthGuidance",
    inputId: "wheelBandwidthInput",
    key: "wheel_bandwidth_pct",
    labelKey: "settings.wheel_bandwidth",
    step: "0.1",
  },
  {
    fallbackLabel: "Driveshaft Bandwidth (%)",
    guidanceId: "driveshaftBandwidthGuidance",
    inputId: "driveshaftBandwidthInput",
    key: "driveshaft_bandwidth_pct",
    labelKey: "settings.driveshaft_bandwidth",
    step: "0.1",
  },
  {
    fallbackLabel: "Engine Bandwidth (%)",
    guidanceId: "engineBandwidthGuidance",
    inputId: "engineBandwidthInput",
    key: "engine_bandwidth_pct",
    labelKey: "settings.engine_bandwidth",
    step: "0.1",
  },
  {
    fallbackLabel: "Min Half-width (Hz)",
    guidanceId: "minAbsBandHzGuidance",
    inputId: "minAbsBandHzInput",
    key: "min_abs_band_hz",
    labelKey: "settings.min_half_width",
    step: "0.1",
  },
  {
    fallbackLabel: "Max Half-width (%)",
    guidanceId: "maxBandHalfWidthGuidance",
    inputId: "maxBandHalfWidthInput",
    key: "max_band_half_width_pct",
    labelKey: "settings.max_half_width",
    step: "0.1",
  },
] as const;

export const UNCERTAINTY_FIELDS: readonly AnalysisFieldSpec[] = [
  {
    fallbackLabel: "Speed Uncertainty (%)",
    guidanceId: "speedUncertaintyGuidance",
    inputId: "speedUncertaintyInput",
    key: "speed_uncertainty_pct",
    labelKey: "settings.speed_uncertainty",
    step: "0.1",
  },
  {
    fallbackLabel: "Tire Diameter Uncertainty (%)",
    guidanceId: "tireDiameterUncertaintyGuidance",
    inputId: "tireDiameterUncertaintyInput",
    key: "tire_diameter_uncertainty_pct",
    labelKey: "settings.tire_diameter_uncertainty",
    step: "0.1",
  },
  {
    fallbackLabel: "Final Drive Uncertainty (%)",
    guidanceId: "finalDriveUncertaintyGuidance",
    inputId: "finalDriveUncertaintyInput",
    key: "final_drive_uncertainty_pct",
    labelKey: "settings.final_drive_uncertainty",
    step: "0.1",
  },
  {
    fallbackLabel: "Gear/Slip Uncertainty (%)",
    guidanceId: "gearUncertaintyGuidance",
    inputId: "gearUncertaintyInput",
    key: "gear_uncertainty_pct",
    labelKey: "settings.gear_slip_uncertainty",
    step: "0.1",
  },
] as const;

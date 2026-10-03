import type { Feedback } from "../../components/feedback";

export interface SettingsAnalysisGuidanceLine {
  label: string;
  value: string;
}

export interface SettingsAnalysisGuidanceRenderModel {
  error: Feedback | null;
  lines: readonly SettingsAnalysisGuidanceLine[];
}

export type AnalysisPanelFieldKey =
  | "speed_uncertainty_pct"
  | "tire_diameter_uncertainty_pct"
  | "final_drive_uncertainty_pct"
  | "gear_uncertainty_pct";

export interface AnalysisPanelFieldRenderModel {
  guidance: SettingsAnalysisGuidanceRenderModel;
  invalid: boolean;
  value: string;
}

export interface AnalysisPanelRenderModel {
  fields: Record<AnalysisPanelFieldKey, AnalysisPanelFieldRenderModel>;
  saveFeedback: Feedback | null;
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

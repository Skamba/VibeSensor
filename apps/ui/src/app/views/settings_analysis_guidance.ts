import type { SettingsFeedbackMessage } from "./settings_feedback";

export interface SettingsAnalysisGuidanceLine {
  label: string;
  value: string;
}

export interface SettingsAnalysisGuidanceOptions {
  lines: readonly SettingsAnalysisGuidanceLine[];
  errorMessage?: string | null;
}

export interface SettingsAnalysisGuidanceRenderModel {
  error: SettingsFeedbackMessage | null;
  lines: readonly SettingsAnalysisGuidanceLine[];
}

export function buildSettingsAnalysisGuidanceRenderModel(
  options: SettingsAnalysisGuidanceOptions,
): SettingsAnalysisGuidanceRenderModel {
  return {
    error: options.errorMessage
      ? {
          body: options.errorMessage,
          compact: true,
          tone: "error",
        }
      : null,
    lines: [...options.lines],
  };
}

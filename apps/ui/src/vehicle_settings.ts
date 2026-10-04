import { defaultAnalysisSettings } from "./constants";

/**
 * Analysis uncertainty tuning. Car references (tire size, final drive, top
 * gear) have no defaults: a car either has them or they are unknown. The key
 * list is pinned against the generated backend defaults by
 * tests/vehicle_settings.spec.ts.
 */

export interface AnalysisTuningSettings {
  speed_uncertainty_pct: number;
  tire_diameter_uncertainty_pct: number;
  final_drive_uncertainty_pct: number;
  gear_uncertainty_pct: number;
}

export const defaultAnalysisTuningSettings: Readonly<AnalysisTuningSettings> = {
  speed_uncertainty_pct: defaultAnalysisSettings.speed_uncertainty_pct,
  tire_diameter_uncertainty_pct:
    defaultAnalysisSettings.tire_diameter_uncertainty_pct,
  final_drive_uncertainty_pct:
    defaultAnalysisSettings.final_drive_uncertainty_pct,
  gear_uncertainty_pct: defaultAnalysisSettings.gear_uncertainty_pct,
};

const analysisTuningSettingKeys = [
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
] as const satisfies readonly (keyof AnalysisTuningSettings)[];

type AnalysisTuningPatch = Partial<
  Record<keyof AnalysisTuningSettings, number | null | undefined>
>;

export function mergeAnalysisTuningSettings(
  current: AnalysisTuningSettings,
  source: AnalysisTuningPatch,
): AnalysisTuningSettings {
  const next = { ...current };
  for (const key of analysisTuningSettingKeys) {
    const value = source[key];
    if (typeof value === "number") {
      next[key] = value;
    }
  }
  return next;
}

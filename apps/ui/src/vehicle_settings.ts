import { defaultAnalysisSettings } from "./constants";

/**
 * Vehicle settings: the active car's drivetrain aspects plus the analysis
 * uncertainty tuning. Key lists are pinned against the generated backend
 * defaults by tests/vehicle_settings.spec.ts.
 */

export interface CarAspectSettings {
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  final_drive_ratio: number;
  current_gear_ratio: number;
  tire_deflection_factor: number;
}

export interface AnalysisTuningSettings {
  speed_uncertainty_pct: number;
  tire_diameter_uncertainty_pct: number;
  final_drive_uncertainty_pct: number;
  gear_uncertainty_pct: number;
}

export interface VehicleSettings
  extends CarAspectSettings,
    AnalysisTuningSettings {}

export const defaultCarAspectSettings: Readonly<CarAspectSettings> = {
  tire_width_mm: defaultAnalysisSettings.tire_width_mm,
  tire_aspect_pct: defaultAnalysisSettings.tire_aspect_pct,
  rim_in: defaultAnalysisSettings.rim_in,
  final_drive_ratio: defaultAnalysisSettings.final_drive_ratio,
  current_gear_ratio: defaultAnalysisSettings.current_gear_ratio,
  tire_deflection_factor: defaultAnalysisSettings.tire_deflection_factor,
};

export const defaultAnalysisTuningSettings: Readonly<AnalysisTuningSettings> = {
  speed_uncertainty_pct: defaultAnalysisSettings.speed_uncertainty_pct,
  tire_diameter_uncertainty_pct:
    defaultAnalysisSettings.tire_diameter_uncertainty_pct,
  final_drive_uncertainty_pct:
    defaultAnalysisSettings.final_drive_uncertainty_pct,
  gear_uncertainty_pct: defaultAnalysisSettings.gear_uncertainty_pct,
};

const carAspectSettingKeys = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
  "final_drive_ratio",
  "current_gear_ratio",
  "tire_deflection_factor",
] as const satisfies readonly (keyof CarAspectSettings)[];

const analysisTuningSettingKeys = [
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
] as const satisfies readonly (keyof AnalysisTuningSettings)[];

type VehicleSettingsNumericPatch = Partial<
  Record<keyof VehicleSettings, number | null | undefined>
>;

export function composeVehicleSettings(
  car: CarAspectSettings,
  analysis: AnalysisTuningSettings,
): VehicleSettings {
  return {
    ...car,
    ...analysis,
  };
}

export function mergeCarAspectSettings(
  current: CarAspectSettings,
  source: VehicleSettingsNumericPatch,
): CarAspectSettings {
  const next = { ...current };
  for (const key of carAspectSettingKeys) {
    const value = source[key];
    if (typeof value === "number") {
      next[key] = value;
    }
  }
  return next;
}

export function mergeAnalysisTuningSettings(
  current: AnalysisTuningSettings,
  source: VehicleSettingsNumericPatch,
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

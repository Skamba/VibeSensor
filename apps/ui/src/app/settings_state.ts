import type {
  CarRecord,
  SpeedSourceKind,
  SpeedSourceStatusPayload,
} from "../api/types";
import { defaultAnalysisSettings } from "../constants";
import { signal } from "./ui_signals";
import type { SignalState } from "./signal_state";

export interface CarAspectSettings {
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  final_drive_ratio: number;
  current_gear_ratio: number;
  tire_deflection_factor: number;
}

export interface AnalysisTuningSettings {
  wheel_bandwidth_pct: number;
  driveshaft_bandwidth_pct: number;
  engine_bandwidth_pct: number;
  speed_uncertainty_pct: number;
  tire_diameter_uncertainty_pct: number;
  final_drive_uncertainty_pct: number;
  gear_uncertainty_pct: number;
  min_abs_band_hz: number;
  max_band_half_width_pct: number;
}

export interface VehicleSettings
  extends CarAspectSettings,
    AnalysisTuningSettings {}

const defaultCarAspectSettings: Readonly<CarAspectSettings> = {
  tire_width_mm: defaultAnalysisSettings.tire_width_mm,
  tire_aspect_pct: defaultAnalysisSettings.tire_aspect_pct,
  rim_in: defaultAnalysisSettings.rim_in,
  final_drive_ratio: defaultAnalysisSettings.final_drive_ratio,
  current_gear_ratio: defaultAnalysisSettings.current_gear_ratio,
  tire_deflection_factor: defaultAnalysisSettings.tire_deflection_factor,
};

const defaultAnalysisTuningSettings: Readonly<AnalysisTuningSettings> = {
  wheel_bandwidth_pct: defaultAnalysisSettings.wheel_bandwidth_pct,
  driveshaft_bandwidth_pct: defaultAnalysisSettings.driveshaft_bandwidth_pct,
  engine_bandwidth_pct: defaultAnalysisSettings.engine_bandwidth_pct,
  speed_uncertainty_pct: defaultAnalysisSettings.speed_uncertainty_pct,
  tire_diameter_uncertainty_pct:
    defaultAnalysisSettings.tire_diameter_uncertainty_pct,
  final_drive_uncertainty_pct:
    defaultAnalysisSettings.final_drive_uncertainty_pct,
  gear_uncertainty_pct: defaultAnalysisSettings.gear_uncertainty_pct,
  min_abs_band_hz: defaultAnalysisSettings.min_abs_band_hz,
  max_band_half_width_pct: defaultAnalysisSettings.max_band_half_width_pct,
};

export const defaultVehicleSettings: Readonly<VehicleSettings> =
  defaultAnalysisSettings;

const carAspectSettingKeys = [
  "tire_width_mm",
  "tire_aspect_pct",
  "rim_in",
  "final_drive_ratio",
  "current_gear_ratio",
  "tire_deflection_factor",
] as const satisfies readonly (keyof CarAspectSettings)[];

const analysisTuningSettingKeys = [
  "wheel_bandwidth_pct",
  "driveshaft_bandwidth_pct",
  "engine_bandwidth_pct",
  "speed_uncertainty_pct",
  "tire_diameter_uncertainty_pct",
  "final_drive_uncertainty_pct",
  "gear_uncertainty_pct",
  "min_abs_band_hz",
  "max_band_half_width_pct",
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

export interface CarSettingsValue {
  activeVehicleSettings: CarAspectSettings;
  cars: CarRecord[];
  carsLoaded: boolean;
  activeCarId: string | null;
}

export interface AnalysisSettingsValue {
  vehicleSettings: AnalysisTuningSettings;
}

export interface SpeedSettingsValue {
  source: SpeedSourceKind;
  manualSpeedKph: number | null;
  obdDeviceMac: string | null;
  obdDeviceName: string | null;
  resolvedSource: SpeedSourceStatusPayload["speed_source"] | null;
  gpsFallbackActive: boolean;
  gpsEffectiveSpeedKph: number | null;
}

export type CarSettingsState = SignalState<CarSettingsValue>;
export type AnalysisSettingsState = SignalState<AnalysisSettingsValue>;
export type SpeedSettingsState = SignalState<SpeedSettingsValue>;

export interface SettingsState {
  car: CarSettingsState;
  analysis: AnalysisSettingsState;
  speed: SpeedSettingsState;
}

export function createSettingsState(): SettingsState {
  return {
    car: {
      activeVehicleSettings: signal<CarAspectSettings>({
        ...defaultCarAspectSettings,
      }),
      cars: signal<CarRecord[]>([]),
      carsLoaded: signal(false),
      activeCarId: signal<string | null>(null),
    },
    analysis: {
      vehicleSettings: signal<AnalysisTuningSettings>({
        ...defaultAnalysisTuningSettings,
      }),
    },
    speed: {
      source: signal<SpeedSourceKind>("gps"),
      manualSpeedKph: signal<number | null>(null),
      obdDeviceMac: signal<string | null>(null),
      obdDeviceName: signal<string | null>(null),
      resolvedSource: signal<SpeedSourceStatusPayload["speed_source"] | null>(
        null,
      ),
      gpsFallbackActive: signal(false),
      gpsEffectiveSpeedKph: signal<number | null>(null),
    },
  };
}

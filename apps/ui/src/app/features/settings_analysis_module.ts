import type { AnalysisSettingsRequest, AnalysisSettingsPayload } from "../../api/types";
import { getAnalysisSettings, setAnalysisSettings } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { SettingsState } from "../ui_app_state";

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

  function syncSettingsInputs(): void {
    if (els.wheelBandwidthInput) els.wheelBandwidthInput.value = String(settings.vehicleSettings.wheel_bandwidth_pct);
    if (els.driveshaftBandwidthInput) els.driveshaftBandwidthInput.value = String(settings.vehicleSettings.driveshaft_bandwidth_pct);
    if (els.engineBandwidthInput) els.engineBandwidthInput.value = String(settings.vehicleSettings.engine_bandwidth_pct);
    if (els.speedUncertaintyInput) els.speedUncertaintyInput.value = String(settings.vehicleSettings.speed_uncertainty_pct);
    if (els.tireDiameterUncertaintyInput) els.tireDiameterUncertaintyInput.value = String(settings.vehicleSettings.tire_diameter_uncertainty_pct);
    if (els.finalDriveUncertaintyInput) els.finalDriveUncertaintyInput.value = String(settings.vehicleSettings.final_drive_uncertainty_pct);
    if (els.gearUncertaintyInput) els.gearUncertaintyInput.value = String(settings.vehicleSettings.gear_uncertainty_pct);
    if (els.minAbsBandHzInput) els.minAbsBandHzInput.value = String(settings.vehicleSettings.min_abs_band_hz);
    if (els.maxBandHalfWidthInput) els.maxBandHalfWidthInput.value = String(settings.vehicleSettings.max_band_half_width_pct);
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
    const wheelBandwidth = Number(els.wheelBandwidthInput?.value);
    const driveshaftBandwidth = Number(els.driveshaftBandwidthInput?.value);
    const engineBandwidth = Number(els.engineBandwidthInput?.value);
    const speedUncertainty = Number(els.speedUncertaintyInput?.value);
    const tireDiameterUncertainty = Number(els.tireDiameterUncertaintyInput?.value);
    const finalDriveUncertainty = Number(els.finalDriveUncertaintyInput?.value);
    const gearUncertainty = Number(els.gearUncertaintyInput?.value);
    const minAbsBandHz = Number(els.minAbsBandHzInput?.value);
    const maxBandHalfWidth = Number(els.maxBandHalfWidthInput?.value);
    const validBandwidths = wheelBandwidth > 0 && wheelBandwidth <= 40 && driveshaftBandwidth > 0 && driveshaftBandwidth <= 40 && engineBandwidth > 0 && engineBandwidth <= 40;
    const validUncertainty = speedUncertainty >= 0 && speedUncertainty <= 20 && tireDiameterUncertainty >= 0 && tireDiameterUncertainty <= 20 && finalDriveUncertainty >= 0 && finalDriveUncertainty <= 10 && gearUncertainty >= 0 && gearUncertainty <= 20;
    const validBandLimits = minAbsBandHz >= 0 && minAbsBandHz <= 10 && maxBandHalfWidth > 0 && maxBandHalfWidth <= 25;
    if (!validBandwidths || !validUncertainty || !validBandLimits) {
      ctx.showError(t("settings.validation_error"));
      return;
    }
    const payload: AnalysisSettingsRequest = {
      wheel_bandwidth_pct: wheelBandwidth,
      driveshaft_bandwidth_pct: driveshaftBandwidth,
      engine_bandwidth_pct: engineBandwidth,
      speed_uncertainty_pct: speedUncertainty,
      tire_diameter_uncertainty_pct: tireDiameterUncertainty,
      final_drive_uncertainty_pct: finalDriveUncertainty,
      gear_uncertainty_pct: gearUncertainty,
      min_abs_band_hz: minAbsBandHz,
      max_band_half_width_pct: maxBandHalfWidth,
    };
    for (const key of ANALYSIS_SETTING_KEYS) {
      if (!(key in payload)) {
        payload[key] = settings.vehicleSettings[key];
      }
    }
    void syncAnalysisSettingsToServer(payload);
  }

  function bindHandlers(): void {
    els.saveAnalysisBtn?.addEventListener("click", saveAnalysisFromInputs);
  }

  return {
    bindHandlers,
    syncSettingsInputs,
    loadAnalysisSettingsFromServer,
    saveAnalysisFromInputs,
  };
}

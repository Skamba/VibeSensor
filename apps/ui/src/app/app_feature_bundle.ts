import type { UiDomElements } from "./ui_dom_registry";
import { createCarsFeature, type CarsFeature } from "./features/cars_feature";
import { createEspFlashFeature, type EspFlashFeature } from "./features/esp_flash_feature";
import { createHistoryFeature, type HistoryFeature } from "./features/history_feature";
import { createRealtimeFeature, type RealtimeFeature } from "./features/realtime_feature";
import { createSettingsFeature, type SettingsFeature } from "./features/settings_feature";
import { createUpdateFeature, type UpdateFeature } from "./features/update_feature";
import type { AppState } from "./ui_app_state";
import { createUiCarCreationCommand } from "./runtime/ui_car_creation_command";
import { createUiRecordingHistoryRefresh } from "./runtime/ui_recording_history_refresh";
import type { AdaptedClient } from "../server_payload";

export interface AppFeatureBundle {
  history: HistoryFeature;
  realtime: RealtimeFeature;
  settings: SettingsFeature;
  cars: CarsFeature;
  update: UpdateFeature;
  espFlash: EspFlashFeature;
}

export interface AppFeatureBundleDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  showError: (message: string) => void;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  setPillState: (el: HTMLElement | null, variant: string, text: string) => void;
  setStatValue: (container: HTMLElement | null, value: string | number) => void;
  renderSpectrum: () => void;
  renderSpeedReadout: () => void;
  renderCarSelectionWarning: () => void;
  sendSelection: () => void;
  locationCodeForClient?: (client: AdaptedClient) => string;
}

export function createAppFeatureBundle(deps: AppFeatureBundleDeps): AppFeatureBundle {
  const { state, els, t, escapeHtml, fmt, fmtTs, formatInt } = deps;

  const history = createHistoryFeature({
    history: state.history,
    getLanguage: () => state.shell.lang,
    els,
    t,
    escapeHtml,
    showError: deps.showError,
    fmt,
    fmtTs,
    formatInt,
  });
  const recordingHistoryRefresh = createUiRecordingHistoryRefresh({
    refreshHistory: () => history.refreshHistory(),
  });

  const realtime = createRealtimeFeature({
    realtime: state.realtime,
    getLanguage: () => state.shell.lang,
    els,
    t,
    escapeHtml,
    showError: deps.showError,
    formatInt,
    setPillState: deps.setPillState,
    setStatValue: deps.setStatValue,
    sendSelection: deps.sendSelection,
    onRecordingStatusChanged: () => recordingHistoryRefresh.onRecordingStatusChanged(),
  });

  const settings = createSettingsFeature({
    settings: state.settings,
    getSpeedUnit: () => state.shell.speedUnit,
    els,
    t,
    escapeHtml,
    showError: deps.showError,
    fmt,
    renderSpectrum: deps.renderSpectrum,
    renderSpeedReadout: deps.renderSpeedReadout,
    onCarSelectionStateChange: deps.renderCarSelectionWarning,
  });
  const carCreation = createUiCarCreationCommand({
    getVehicleSettings: () => state.settings.vehicleSettings,
    syncCarsPayload: (payload) => settings.syncCarsPayload(payload),
    syncActiveCarToInputs: () => settings.syncActiveCarToInputs(),
    renderCarList: () => settings.renderCarList(),
    renderSpectrum: deps.renderSpectrum,
  });

  const cars = createCarsFeature({
    els,
    t,
    escapeHtml,
    showError: deps.showError,
    fmt,
    addCarFromWizard: (name, carType, aspects, variant) =>
      carCreation.addCarFromWizard(name, carType, aspects, variant),
  });

  const update = createUpdateFeature({ els, t, escapeHtml, showError: deps.showError });
  const espFlash = createEspFlashFeature({ els, t, escapeHtml, showError: deps.showError });

  return {
    history,
    realtime,
    settings,
    cars,
    update,
    espFlash,
  };
}

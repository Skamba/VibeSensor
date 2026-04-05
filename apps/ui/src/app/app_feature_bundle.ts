import type { UiCarsDom } from "./dom/cars_dom";
import type { UiEspFlashDom } from "./dom/esp_flash_dom";
import type { UiHistoryDom } from "./dom/history_dom";
import type { UiRealtimeDom } from "./dom/realtime_dom";
import type { UiSettingsDom } from "./dom/settings_dom";
import type { UiShellDom } from "./dom/shell_dom";
import type { UiUpdateDom } from "./dom/update_dom";
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
  shellDom: UiShellDom;
  realtimeDom: UiRealtimeDom;
  historyDom: UiHistoryDom;
  settingsDom: UiSettingsDom;
  carsDom: UiCarsDom;
  updateDom: UiUpdateDom;
  espFlashDom: UiEspFlashDom;
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
  sendSelection: () => void;
  locationCodeForClient?: (client: AdaptedClient) => string;
}

export function createAppFeatureBundle(deps: AppFeatureBundleDeps): AppFeatureBundle {
  const {
    state,
    shellDom,
    realtimeDom,
    historyDom,
    settingsDom,
    carsDom,
    updateDom,
    espFlashDom,
    t,
    escapeHtml,
    fmt,
    fmtTs,
    formatInt,
  } = deps;

  const history = createHistoryFeature({
    history: state.history,
    getLanguage: () => state.shell.lang,
    dom: historyDom,
    shellDom,
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
    spectrum: state.spectrum,
    settings: state.settings,
    getLanguage: () => state.shell.lang,
    dom: realtimeDom,
    shellDom,
    settingsDom,
    carsDom,
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
    dom: settingsDom,
    shellDom,
    carsDom,
    t,
    escapeHtml,
    showError: deps.showError,
    fmt,
    renderSpectrum: deps.renderSpectrum,
    renderSpeedReadout: deps.renderSpeedReadout,
    renderRealtimeStatus: () => realtime.renderStatus(),
    renderRealtimeLoggingStatus: () => realtime.renderLoggingStatus(),
  });
  const carCreation = createUiCarCreationCommand({
    getVehicleSettings: () => state.settings.vehicleSettings,
    syncCarsPayload: (payload) => settings.syncCarsPayload(payload),
    syncActiveCarToInputs: () => settings.syncActiveCarToInputs(),
    showCarCreationSuccess: (carId, carName) => settings.showCarCreationSuccess(carId, carName),
    renderCarList: () => settings.renderCarList(),
    renderSpectrum: deps.renderSpectrum,
  });

  const cars = createCarsFeature({
    dom: carsDom,
    t,
    escapeHtml,
    showError: deps.showError,
    fmt,
    addCarFromWizard: (name, carType, aspects, variant) =>
      carCreation.addCarFromWizard(name, carType, aspects, variant),
  });

  const update = createUpdateFeature({ dom: updateDom, t, escapeHtml, showError: deps.showError });
  const espFlash = createEspFlashFeature({ dom: espFlashDom, t, escapeHtml, showError: deps.showError });

  return {
    history,
    realtime,
    settings,
    cars,
    update,
    espFlash,
  };
}

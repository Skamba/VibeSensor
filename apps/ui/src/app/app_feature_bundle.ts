import type { UiCarsDom } from "./dom/cars_dom";
import type { UiEspFlashDom } from "./dom/esp_flash_dom";
import type { UiHistoryDom } from "./dom/history_dom";
import type { UiRealtimeDom } from "./dom/realtime_dom";
import type { UiSettingsDom } from "./dom/settings_dom";
import type { UiShellDom } from "./dom/shell_dom";
import type { UiUpdateDom } from "./dom/update_dom";
import {
  createAppFeaturePorts,
  createRealtimeFeatureRecordingPorts,
  createSettingsFeatureRealtimePorts,
  type AppFeatureBundle,
} from "./app_feature_ports";
import { createCarsFeature, type CarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import { createHistoryFeature } from "./features/history_feature";
import type { CarsPanelView } from "./views/cars_panel";
import type { HistoryPanelView } from "./views/history_table_view";
import {
  createRealtimeFeature,
  type RealtimeFeatureChromePorts,
  type RealtimeFeatureSelectionPorts,
} from "./features/realtime_feature";
import {
  createSettingsFeature,
  type SettingsFeature,
  type SettingsFeatureViewPorts,
} from "./features/settings_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { AppState } from "./ui_app_state";
import { createUiCarCreationCommand } from "./runtime/ui_car_creation_command";
import type { AnalysisPanelView } from "./views/analysis_panel";
import type { SensorsPanelView } from "./views/sensors_panel";
import type { SpeedSourcePanelView } from "./views/speed_source_panel";

export type { AppFeatureBundle } from "./app_feature_ports";

export interface AppFeatureBundleDom {
  shell: UiShellDom;
  realtime: UiRealtimeDom;
  history: UiHistoryDom;
  settings: UiSettingsDom;
  cars: UiCarsDom;
  update: UiUpdateDom;
  espFlash: UiEspFlashDom;
}

export interface AppFeatureBundleSharedDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  showError: (message: string) => void;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}

export interface AppFeatureBundleRuntimePorts {
  analysisPanel: AnalysisPanelView;
  carsPanel: CarsPanelView;
  sensorsPanel: SensorsPanelView;
  speedSourcePanel: SpeedSourcePanelView;
  realtimeChrome: RealtimeFeatureChromePorts;
  historyPanel: HistoryPanelView;
  transport: RealtimeFeatureSelectionPorts;
  view: SettingsFeatureViewPorts;
}

export interface AppFeatureBundleDeps {
  state: AppState;
  dom: AppFeatureBundleDom;
  shared: AppFeatureBundleSharedDeps;
  runtime: AppFeatureBundleRuntimePorts;
}

export function createAppFeatureBundle(
  deps: AppFeatureBundleDeps,
): AppFeatureBundle {
  const {
    state,
    dom: {
      shell: shellDom,
      realtime: realtimeDom,
      history: historyDom,
      settings: settingsDom,
      cars: carsDom,
      update: updateDom,
      espFlash: espFlashDom,
    },
    shared: { t, escapeHtml, showError, fmt, fmtTs, formatInt },
    runtime,
  } = deps;

  const history = createHistoryFeature({
    history: state.history,
    getLanguage: () => state.shell.lang,
    dom: historyDom,
    panel: runtime.historyPanel,
    shellDom,
    t,
    escapeHtml,
    showError,
    fmt,
    fmtTs,
    formatInt,
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
    showError,
    formatInt,
    chrome: runtime.realtimeChrome,
    sensorsPanel: runtime.sensorsPanel,
    selection: runtime.transport,
    recording: createRealtimeFeatureRecordingPorts(history),
  });

  let carsFeature: CarsFeature | null = null;
  const settings: SettingsFeature = createSettingsFeature({
    settings: state.settings,
    getSpeedUnit: () => state.shell.speedUnit,
    analysisPanel: runtime.analysisPanel,
    carsPanel: runtime.carsPanel.list,
    speedSourcePanel: runtime.speedSourcePanel,
    dom: settingsDom,
    shellDom,
    openCarWizard: () => {
      carsFeature?.openWizard();
    },
    t,
    escapeHtml,
    showError,
    fmt,
    view: runtime.view,
    realtime: createSettingsFeatureRealtimePorts(realtime),
  });

  const carCreation = createUiCarCreationCommand({
    getVehicleSettings: () => state.settings.vehicleSettings,
    syncCarsPayload: (payload) => settings.syncCarsPayload(payload),
    syncActiveCarToInputs: () => settings.syncActiveCarToInputs(),
    showCarCreationSuccess: (carId, carName) =>
      settings.showCarCreationSuccess(carId, carName),
    renderCarList: () => settings.renderCarList(),
    renderSpectrum: runtime.view.renderSpectrum,
  });

  const cars: CarsFeature = createCarsFeature({
    panel: runtime.carsPanel.wizard,
    t,
    escapeHtml,
    showError,
    fmt,
    addCarFromWizard: (name, carType, aspects, variant) =>
      carCreation.addCarFromWizard(name, carType, aspects, variant),
  });
  carsFeature = cars;

  const update = createUpdateFeature({
    dom: updateDom,
    t,
    escapeHtml,
    showError,
  });
  const espFlash = createEspFlashFeature({
    dom: espFlashDom,
    t,
    escapeHtml,
    showError,
  });

  return createAppFeaturePorts({
    history,
    realtime,
    settings,
    cars,
    update,
    espFlash,
  });
}

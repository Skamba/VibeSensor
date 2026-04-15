import {
  createAppFeaturePorts,
  createRealtimeFeatureRecordingPorts,
  createSettingsFeatureRealtimePorts,
  type AppFeatureBundle,
} from "./app_feature_ports";
import { createCarsFeature, type CarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import { createHistoryFeature } from "./features/history_feature";
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
import type { UiMountedPanels } from "./ui_panel_bootstrap";

export type { AppFeatureBundle } from "./app_feature_ports";

export interface AppFeatureBundleSharedDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  showError: (message: string) => void;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}

export interface AppFeatureBundleRuntimePorts {
  panels: UiMountedPanels;
  navigation: {
    activatePrimaryView(viewId: string): void;
    subscribeActiveViewChanges(listener: (viewId: string) => void): () => void;
  };
  realtimeChrome: Pick<RealtimeFeatureChromePorts, "setShellLiveStatus">;
  transport: RealtimeFeatureSelectionPorts;
  view: SettingsFeatureViewPorts;
}

export interface AppFeatureBundleDeps {
  state: AppState;
  shared: AppFeatureBundleSharedDeps;
  runtime: AppFeatureBundleRuntimePorts;
}

export function createAppFeatureBundle(
  deps: AppFeatureBundleDeps,
): AppFeatureBundle {
  const {
    state,
    shared: { t, escapeHtml, showError, fmt, fmtTs, formatInt },
    runtime,
  } = deps;
  const { panels } = runtime;

  const history = createHistoryFeature({
    history: state.history,
    getLanguage: () => state.shell.lang,
    panel: panels.history,
    navigation: runtime.navigation,
    t,
    escapeHtml,
    showError,
    fmt,
    fmtTs,
    formatInt,
  });

  let carsFeature: CarsFeature | null = null;
  const realtime = createRealtimeFeature({
    realtime: state.realtime,
    spectrum: state.spectrum,
    settings: state.settings,
    getLanguage: () => state.shell.lang,
    t,
    escapeHtml,
    showError,
    formatInt,
    chrome: {
      ...runtime.realtimeChrome,
      liveOverview: panels.dashboard.liveOverview,
      loggingPanel: panels.dashboard.logging,
    },
    sensorsPanel: panels.settings.sensors,
    navigation: {
      activatePrimaryView: runtime.navigation.activatePrimaryView,
      activateSettingsTab: (tabId) => panels.settingsShell.activateTab(tabId),
      openCarWizard: () => {
        carsFeature?.openWizard();
      },
    },
    selection: runtime.transport,
    recording: createRealtimeFeatureRecordingPorts(history),
  });

  const settings: SettingsFeature = createSettingsFeature({
    settings: state.settings,
    getSpeedUnit: () => state.shell.speedUnit,
    settingsShell: panels.settingsShell,
    analysisPanel: panels.settings.analysis,
    carsPanel: panels.settings.cars.list,
    speedSourcePanel: panels.settings.speedSource,
    openCarWizard: () => {
      carsFeature?.openWizard();
    },
    t,
    escapeHtml,
    showError,
    fmt,
    subscribePrimaryViewChanges: runtime.navigation.subscribeActiveViewChanges,
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
    panel: panels.settings.cars.wizard,
    t,
    escapeHtml,
    showError,
    fmt,
    addCarFromWizard: (name, carType, aspects, variant) =>
      carCreation.addCarFromWizard(name, carType, aspects, variant),
  });
  carsFeature = cars;

  const update = createUpdateFeature({
    panel: panels.settings.update,
    internetPanel: panels.settings.internet,
    t,
    escapeHtml,
    showError,
  });
  const espFlash = createEspFlashFeature({
    panel: panels.settings.espFlash,
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

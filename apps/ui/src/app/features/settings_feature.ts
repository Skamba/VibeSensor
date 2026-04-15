import type { FeatureDepsBase } from "../feature_deps_base";
import { createCarSelectionDerivedState } from "../car_selection_state";
import type { SettingsState } from "../ui_app_state";
import type { CarsPayload } from "../../transport/http_models";
import {
  createSettingsAnalysisModule,
  type SettingsAnalysisModule,
} from "./settings_analysis_module";
import {
  createSettingsGpsStatusModule,
  type SettingsGpsStatusModule,
} from "./settings_gps_status_module";
import {
  createSettingsSpeedSourceModule,
  type SettingsSpeedSourceModule,
} from "./settings_speed_source_module";
import {
  createSettingsCarsModule,
  type SettingsCarsModule,
} from "./settings_cars_module";
import type { CarsListPanelView } from "../views/cars_panel";
import type { AnalysisPanelView } from "../views/analysis_panel";
import type { SettingsShellView } from "../views/settings_shell";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";

export interface SettingsFeatureDeps extends FeatureDepsBase {
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  openCarWizard: () => void;
  subscribePrimaryViewChanges(listener: (viewId: string) => void): () => void;
  settingsShell: SettingsShellView;
  carsPanel: CarsListPanelView;
  analysisPanel: AnalysisPanelView;
  speedSourcePanel: SpeedSourcePanelView;
  view: SettingsFeatureViewPorts;
  realtime: SettingsFeatureRealtimePorts;
}

export interface SettingsFeatureViewPorts {
  renderSpectrum: () => void;
  renderSpeedReadout: () => void;
}

export interface SettingsFeatureRealtimePorts {
  renderRealtimeStatus: () => void;
  renderRealtimeLoggingStatus: () => void;
}

export interface SettingsFeature {
  bindHandlers(): void;
  syncSettingsInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  loadAnalysisSettingsFromServer(): Promise<void>;
  loadCarsFromServer(): Promise<void>;
  renderCarList(): void;
  syncCarsPayload(payload: CarsPayload): void;
  syncActiveCarToInputs(): void;
  showCarCreationSuccess(carId: string, carName: string): void;
  saveAnalysisFromInputs(): void;
  saveSpeedSourceFromInputs(): void;
  startGpsStatusPolling(): void;
  stopGpsStatusPolling(): void;
}

export function createSettingsFeature(
  ctx: SettingsFeatureDeps,
): SettingsFeature {
  const { settings, t, escapeHtml, fmt } = ctx;
  const carSelection = createCarSelectionDerivedState(settings);
  let handlersBound = false;
  let carsModule!: SettingsCarsModule;

  function showSettingsSaveError(error: unknown): void {
    ctx.showError(
      error instanceof Error ? error.message : t("settings.save_failed"),
    );
  }

  function openSettingsTab(tabId: string): void {
    ctx.settingsShell.activateTab(tabId);
  }

  const analysisModule: SettingsAnalysisModule = createSettingsAnalysisModule({
    panel: ctx.analysisPanel,
    t,
    escapeHtml,
    showError: ctx.showError,
    settings,
    renderSpectrum: ctx.view.renderSpectrum,
    hasValidActiveCar: () => carSelection.hasResolvedActiveCar.value,
    onMissingActiveCar: () => carsModule.renderCarList(),
    onSaveError: showSettingsSaveError,
  });
  const speedSourceModule: SettingsSpeedSourceModule =
    createSettingsSpeedSourceModule({
      panel: ctx.speedSourcePanel,
      t,
      escapeHtml,
      showError: ctx.showError,
      settings,
      getSpeedUnit: ctx.getSpeedUnit,
      fmt,
      renderSpeedReadout: ctx.view.renderSpeedReadout,
      subscribePrimaryViewChanges: ctx.subscribePrimaryViewChanges,
      subscribeSettingsTabChanges: ctx.settingsShell.subscribeActiveTabChanges,
    });
  const gpsStatusModule: SettingsGpsStatusModule =
    createSettingsGpsStatusModule({
      panel: ctx.speedSourcePanel,
      t,
      escapeHtml,
      showError: ctx.showError,
      settings,
      getSpeedUnit: ctx.getSpeedUnit,
      fmt,
      syncSpeedSourceSelectionUi: speedSourceModule.syncSpeedSourceSelectionUi,
      renderSpeedReadout: ctx.view.renderSpeedReadout,
  });
  carsModule = createSettingsCarsModule({
    analysisPanel: ctx.analysisPanel,
    escapeHtml,
    fmt,
    openAnalysisTab: () => openSettingsTab("analysisTab"),
    openCarWizard: ctx.openCarWizard,
    renderRealtimeLoggingStatus: ctx.realtime.renderRealtimeLoggingStatus,
    renderRealtimeStatus: ctx.realtime.renderRealtimeStatus,
    renderSpectrum: ctx.view.renderSpectrum,
    settings,
    subscribePrimaryViewChanges: ctx.subscribePrimaryViewChanges,
    subscribeSettingsTabChanges: ctx.settingsShell.subscribeActiveTabChanges,
    showError: ctx.showError,
    syncAnalysisInputs: analysisModule.syncSettingsInputs,
    panel: ctx.carsPanel,
    t,
  });

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    carsModule.bindHandlers();
    analysisModule.bindHandlers();
    speedSourceModule.bindHandlers();
  }

  return {
    bindHandlers,
    syncSettingsInputs: analysisModule.syncSettingsInputs,
    loadSpeedSourceFromServer: speedSourceModule.loadSpeedSourceFromServer,
    loadAnalysisSettingsFromServer:
      analysisModule.loadAnalysisSettingsFromServer,
    loadCarsFromServer: carsModule.loadCarsFromServer,
    renderCarList: carsModule.renderCarList,
    syncCarsPayload(payload: CarsPayload): void {
      carsModule.syncCarsPayload(payload);
    },
    syncActiveCarToInputs: carsModule.syncActiveCarToInputs,
    showCarCreationSuccess(carId: string, carName: string): void {
      carsModule.showCarCreationSuccess(carId, carName);
    },
    saveAnalysisFromInputs: analysisModule.saveAnalysisFromInputs,
    saveSpeedSourceFromInputs: speedSourceModule.saveSpeedSourceFromInputs,
    startGpsStatusPolling: gpsStatusModule.startGpsStatusPolling,
    stopGpsStatusPolling: gpsStatusModule.stopGpsStatusPolling,
  };
}

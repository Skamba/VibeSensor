import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import { createCarSelectionDerivedState } from "../car_selection_state";
import type { SettingsState, ShellState } from "../ui_app_state";
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

interface SettingsFeatureStateDeps {
  settings: SettingsState;
  shell: Pick<ShellState, "speedUnit">;
}

interface SettingsFeaturePanelDeps {
  settingsShell: SettingsShellView;
  carsPanel: CarsListPanelView;
  analysisPanel: AnalysisPanelView;
  speedSourcePanel: SpeedSourcePanelView;
}

interface SettingsFeaturePortDeps {
  openCarWizard: () => void;
  subscribePrimaryViewChanges(listener: (viewId: string) => void): () => void;
  view: SettingsFeatureViewPorts;
  realtime: SettingsFeatureRealtimePorts;
}

export interface SettingsFeatureDeps {
  state: SettingsFeatureStateDeps;
  panels: SettingsFeaturePanelDeps;
  ports: SettingsFeaturePortDeps;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "fmt">;
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
  const { services, formatting } = ctx;
  const settings = ctx.state.settings;
  const carSelection = createCarSelectionDerivedState(settings);
  let handlersBound = false;
  let carsModule!: SettingsCarsModule;

  function showSettingsSaveError(error: unknown): void {
    services.showError(
      error instanceof Error ? error.message : services.t("settings.save_failed"),
    );
  }

  function openSettingsTab(tabId: string): void {
    ctx.panels.settingsShell.activateTab(tabId);
  }

  const analysisModule: SettingsAnalysisModule = createSettingsAnalysisModule({
    panel: ctx.panels.analysisPanel,
    settings,
    services,
    renderSpectrum: ctx.ports.view.renderSpectrum,
    hasValidActiveCar: () => carSelection.hasResolvedActiveCar.value,
    onMissingActiveCar: () => carsModule.renderCarList(),
    onSaveError: showSettingsSaveError,
  });
  const speedSourceModule: SettingsSpeedSourceModule =
    createSettingsSpeedSourceModule({
      panel: ctx.panels.speedSourcePanel,
      settings,
      services,
      formatting,
      getSpeedUnit: () => ctx.state.shell.speedUnit,
      ports: {
        renderSpeedReadout: ctx.ports.view.renderSpeedReadout,
        subscribePrimaryViewChanges: ctx.ports.subscribePrimaryViewChanges,
        subscribeSettingsTabChanges:
          ctx.panels.settingsShell.subscribeActiveTabChanges,
      },
    });
  const gpsStatusModule: SettingsGpsStatusModule =
    createSettingsGpsStatusModule({
      panel: ctx.panels.speedSourcePanel,
      settings,
      services: {
        t: services.t,
      },
      formatting,
      getSpeedUnit: () => ctx.state.shell.speedUnit,
      ports: {
        syncSpeedSourceSelectionUi: speedSourceModule.syncSpeedSourceSelectionUi,
        renderSpeedReadout: ctx.ports.view.renderSpeedReadout,
      },
    });
  carsModule = createSettingsCarsModule({
    settings,
    panels: {
      analysisPanel: ctx.panels.analysisPanel,
      panel: ctx.panels.carsPanel,
    },
    ports: {
      openAnalysisTab: () => openSettingsTab("analysisTab"),
      openCarWizard: ctx.ports.openCarWizard,
      renderRealtimeLoggingStatus: ctx.ports.realtime.renderRealtimeLoggingStatus,
      renderRealtimeStatus: ctx.ports.realtime.renderRealtimeStatus,
      renderSpectrum: ctx.ports.view.renderSpectrum,
      subscribePrimaryViewChanges: ctx.ports.subscribePrimaryViewChanges,
      subscribeSettingsTabChanges:
        ctx.panels.settingsShell.subscribeActiveTabChanges,
      syncAnalysisInputs: analysisModule.syncSettingsInputs,
    },
    services,
    formatting,
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

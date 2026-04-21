import type { QueryClient } from "@tanstack/query-core";

import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import { createCarSelectionDerivedState } from "../car_selection_state";
import type { SettingsState, ShellState } from "../ui_app_state";
import { effectOnChange, untracked, type ReadonlySignal } from "../ui_signals";
import type { CarsPayload } from "../../api/types";
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
  shell: Pick<ShellState, "lang" | "speedUnit">;
}

interface SettingsFeaturePanelDeps {
  settingsShell: SettingsShellView;
  carsPanel: CarsListPanelView;
  analysisPanel: AnalysisPanelView;
  speedSourcePanel: SpeedSourcePanelView;
}

interface SettingsFeaturePortDeps {
  openCarWizard: () => void;
  activeViewId: ReadonlySignal<string>;
  view: SettingsFeatureViewPorts;
}

export interface SettingsFeatureDeps {
  state: SettingsFeatureStateDeps;
  panels: SettingsFeaturePanelDeps;
  ports: SettingsFeaturePortDeps;
  queryClient: QueryClient;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "fmt">;
}

export interface SettingsFeatureViewPorts {
  renderSpectrum: () => void;
  refreshSpectrumDecorations: () => void;
}

export interface SettingsFeature {
  addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number>,
    variant?: string,
  ): Promise<void>;
  bindHandlers(): void;
  dispose(): void;
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
}

export function createSettingsFeature(
  ctx: SettingsFeatureDeps,
): SettingsFeature {
  const { services, formatting } = ctx;
  const settings = ctx.state.settings;
  const carSelection = createCarSelectionDerivedState(settings.car);
  let handlersBound = false;
  let carsModule!: SettingsCarsModule;

  function showSettingsSaveError(error: unknown): void {
    services.showError(
      error instanceof Error
        ? error.message
        : services.t("settings.save_failed"),
    );
  }

  function openSettingsTab(tabId: string): void {
    ctx.panels.settingsShell.activateTab(tabId);
  }

  const analysisModule: SettingsAnalysisModule = createSettingsAnalysisModule({
    panel: ctx.panels.analysisPanel,
    settings,
    queryClient: ctx.queryClient,
    services,
    refreshSpectrumDecorations: ctx.ports.view.refreshSpectrumDecorations,
    hasValidActiveCar: () => carSelection.hasResolvedActiveCar.value,
    onMissingActiveCar: () => carsModule.renderCarList(),
    onSaveError: showSettingsSaveError,
  });
  const speedSourceModule: SettingsSpeedSourceModule =
    createSettingsSpeedSourceModule({
      panel: ctx.panels.speedSourcePanel,
      settings,
      queryClient: ctx.queryClient,
      services,
      formatting,
      getSpeedUnit: () => ctx.state.shell.speedUnit.value,
      ports: {
        activeViewId: ctx.ports.activeViewId,
        activeSettingsTabId: ctx.panels.settingsShell.activeTabId,
      },
    });
  const gpsStatusModule: SettingsGpsStatusModule =
    createSettingsGpsStatusModule({
      panel: ctx.panels.speedSourcePanel,
      settings,
      queryClient: ctx.queryClient,
      services: {
        t: services.t,
      },
      formatting,
      getSpeedUnit: () => ctx.state.shell.speedUnit.value,
      ports: {
        activeViewId: ctx.ports.activeViewId,
        activeSettingsTabId: ctx.panels.settingsShell.activeTabId,
        syncSpeedSourceSelectionUi:
          speedSourceModule.syncSpeedSourceSelectionUi,
      },
    });
  carsModule = createSettingsCarsModule({
    settings,
    queryClient: ctx.queryClient,
    panels: {
      analysisPanel: ctx.panels.analysisPanel,
      panel: ctx.panels.carsPanel,
    },
    ports: {
      openAnalysisTab: () => openSettingsTab("analysisTab"),
      openCarWizard: ctx.ports.openCarWizard,
      activeViewId: ctx.ports.activeViewId,
      activeSettingsTabId: ctx.panels.settingsShell.activeTabId,
      refreshSpectrumDecorations: ctx.ports.view.refreshSpectrumDecorations,
      syncAnalysisInputs: analysisModule.syncSettingsInputs,
    },
    services,
    formatting,
  });

  const disposeLanguageSync = effectOnChange(ctx.state.shell.lang, () => {
    untracked(() => {
      analysisModule.syncSettingsInputs();
    });
  });

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    carsModule.bindHandlers();
    analysisModule.bindHandlers();
    speedSourceModule.bindHandlers();
    gpsStatusModule.bindHandlers();
  }

  async function loadSpeedSourceFromServer(): Promise<void> {
    try {
      await speedSourceModule.loadSpeedSourceFromServer();
    } finally {
      await gpsStatusModule.markStartupReady();
    }
  }

  return {
    addCarFromWizard: carsModule.addCarFromWizard,
    bindHandlers,
    dispose(): void {
      disposeLanguageSync();
      gpsStatusModule.dispose();
      speedSourceModule.dispose();
      carsModule.dispose();
    },
    syncSettingsInputs: analysisModule.syncSettingsInputs,
    loadSpeedSourceFromServer,
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
  };
}

import type { QueryClient } from "@tanstack/query-core";

import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import { createCarSelectionDerivedState } from "../car_selection_state";
import type { SettingsState } from "../settings_state";
import type { ShellState } from "../shell_state";
import { effectOnChange, untracked, type ReadonlySignal } from "../ui_signals";
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
import type { AnalysisPanelView } from "../views/analysis_panel";
import type { SettingsShellView } from "../views/settings_shell";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";

interface SettingsFeatureStateDeps {
  settings: SettingsState;
  shell: Pick<ShellState, "lang" | "speedUnit">;
}

interface SettingsFeaturePanelDeps {
  settingsShell: SettingsShellView;
  analysisPanel: AnalysisPanelView;
  speedSourcePanel: SpeedSourcePanelView;
}

interface SettingsFeaturePortDeps {
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
  bindHandlers(): void;
  dispose(): void;
  syncSettingsInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  loadAnalysisSettingsFromServer(): Promise<void>;
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

  function showSettingsSaveError(error: unknown): void {
    services.showError(
      error instanceof Error
        ? error.message
        : services.t("settings.save_failed"),
    );
  }

  const analysisModule: SettingsAnalysisModule = createSettingsAnalysisModule({
    panel: ctx.panels.analysisPanel,
    settings,
    queryClient: ctx.queryClient,
    services,
    refreshSpectrumDecorations: ctx.ports.view.refreshSpectrumDecorations,
    hasValidActiveCar: () => carSelection.hasResolvedActiveCar.value,
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
    bindHandlers,
    dispose(): void {
      disposeLanguageSync();
      gpsStatusModule.dispose();
      speedSourceModule.dispose();
      analysisModule.dispose();
    },
    syncSettingsInputs: analysisModule.syncSettingsInputs,
    loadSpeedSourceFromServer,
    loadAnalysisSettingsFromServer:
      analysisModule.loadAnalysisSettingsFromServer,
    saveAnalysisFromInputs: analysisModule.saveAnalysisFromInputs,
    saveSpeedSourceFromInputs: speedSourceModule.saveSpeedSourceFromInputs,
  };
}

import { createCarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import {
  createHistoryFeature,
  type HistoryFeature,
} from "./features/history_feature";
import { createSettingsAnalysisModule } from "./features/settings_analysis_module";
import { createSpeedSourceFeature } from "./features/speed_source_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { AppFeatureBundleDeps } from "./app_feature_bundle";

export interface AppFeatureSecondaryBundle {
  dispose(): void;
  history: Pick<HistoryFeature, "refreshHistory">;
  openCarWizard(): void;
  settings: {
    loadAnalysisSettingsFromServer(): Promise<void>;
    loadSpeedSourceFromServer(): Promise<void>;
  };
}

export function createAppFeatureSecondaryBundle(
  deps: AppFeatureBundleDeps,
): AppFeatureSecondaryBundle {
  const {
    state,
    shared: { services, formatting, serverState },
    runtime,
  } = deps;
  const { panels } = runtime;

  const history = createHistoryFeature({
    history: state.history,
    shell: state.shell,
    panel: panels.history,
    navigation: runtime.navigation,
    services,
    formatting,
    queryClient: serverState.queryClient,
  });

  const analysis = createSettingsAnalysisModule({
    panel: panels.settings.analysis,
    settings: state.settings,
    lang: state.shell.lang,
    queryClient: serverState.queryClient,
    services,
    refreshSpectrumDecorations: runtime.view.refreshSpectrumDecorations,
  });

  const speedSource = createSpeedSourceFeature({
    panel: panels.settings.speedSource,
    settings: state.settings,
    queryClient: serverState.queryClient,
    services,
    formatting: {
      fmt: formatting.fmt,
    },
    getSpeedUnit: () => state.shell.speedUnit.value,
    activeViewId: runtime.navigation.activeViewId,
    activeSettingsTabId: panels.settingsShell.activeTabId,
  });

  const cars = createCarsFeature({
    settings: state.settings,
    queryClient: serverState.queryClient,
    panel: panels.settings.cars,
    analysisPanel: panels.settings.analysis,
    activeViewId: runtime.navigation.activeViewId,
    activeSettingsTabId: panels.settingsShell.activeTabId,
    openAnalysisTab: () => panels.settingsShell.activateTab("analysisTab"),
    refreshSpectrumDecorations: runtime.view.refreshSpectrumDecorations,
    syncAnalysisInputs: analysis.syncSettingsInputs,
    services,
    formatting: {
      fmt: formatting.fmt,
    },
  });

  const update = createUpdateFeature({
    panels: {
      update: panels.settings.update,
      internet: panels.settings.internet,
    },
    ports: {
      activeViewId: runtime.navigation.activeViewId,
      activeSettingsTabId: panels.settingsShell.activeTabId,
    },
    services,
    queryClient: serverState.queryClient,
  });

  const espFlash = createEspFlashFeature({
    panel: panels.settings.espFlash,
    ports: {
      activeViewId: runtime.navigation.activeViewId,
      activeSettingsTabId: panels.settingsShell.activeTabId,
    },
    services,
    queryClient: serverState.queryClient,
  });

  cars.bindHandlers();
  analysis.bindHandlers();
  speedSource.bindHandlers();
  history.bindHandlers();
  update.bindUpdateHandlers();
  espFlash.bindHandlers();

  return {
    dispose(): void {
      espFlash.dispose();
      update.dispose();
      history.dispose();
      speedSource.dispose();
      analysis.dispose();
      cars.dispose();
    },
    history: {
      refreshHistory: () => history.refreshHistory(),
    },
    openCarWizard(): void {
      void cars.openWizard();
    },
    settings: {
      loadSpeedSourceFromServer: () => speedSource.loadSpeedSourceFromServer(),
      loadAnalysisSettingsFromServer: () =>
        analysis.loadAnalysisSettingsFromServer(),
    },
  };
}

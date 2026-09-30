import { createCarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import {
  createHistoryFeature,
  type HistoryFeature,
} from "./features/history_feature";
import {
  createSettingsFeature,
  type SettingsFeature,
} from "./features/settings_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { AppFeatureBundleDeps } from "./app_feature_bundle";

export interface AppFeatureSecondaryBundle {
  dispose(): void;
  history: Pick<HistoryFeature, "refreshHistory">;
  openCarWizard(): void;
  settings: Pick<
    SettingsFeature,
    "loadAnalysisSettingsFromServer" | "loadSpeedSourceFromServer"
  >;
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

  const settings = createSettingsFeature({
    state: {
      settings: state.settings,
      shell: state.shell,
    },
    panels: {
      settingsShell: panels.settingsShell,
      analysisPanel: panels.settings.analysis,
      speedSourcePanel: panels.settings.speedSource,
    },
    ports: {
      activeViewId: runtime.navigation.activeViewId,
      view: runtime.view,
    },
    services,
    formatting: {
      fmt: formatting.fmt,
    },
    queryClient: serverState.queryClient,
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
    syncAnalysisInputs: settings.syncSettingsInputs,
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
  settings.bindHandlers();
  history.bindHandlers();
  update.bindUpdateHandlers();
  espFlash.bindHandlers();

  return {
    dispose(): void {
      espFlash.dispose();
      update.dispose();
      history.dispose();
      settings.dispose();
      cars.dispose();
    },
    history: {
      refreshHistory: () => history.refreshHistory(),
    },
    openCarWizard(): void {
      void cars.openWizard();
    },
    settings: {
      loadSpeedSourceFromServer: () => settings.loadSpeedSourceFromServer(),
      loadAnalysisSettingsFromServer: () =>
        settings.loadAnalysisSettingsFromServer(),
    },
  };
}

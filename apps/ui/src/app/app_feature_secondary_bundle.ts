import { createCarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import {
  createHistoryFeature,
  type HistoryFeature,
} from "./features/history_feature";
import { createSettingsAnalysisModule } from "./features/settings_analysis_module";
import { createSpeedSourceFeature } from "./features/speed_source_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { AppFeatureContext } from "./app_feature_bundle";

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
  ctx: AppFeatureContext,
): AppFeatureSecondaryBundle {
  const { state, services, formatting, panels } = ctx;

  const history = createHistoryFeature({
    history: state.history,
    shell: state.shell,
    panel: panels.history,
    navigation: { activatePrimaryView: ctx.activatePrimaryView },
    services,
    formatting,
    queryClient: ctx.queryClient,
  });

  const analysis = createSettingsAnalysisModule({
    panel: panels.settings.analysis,
    settings: state.settings,
    lang: state.shell.lang,
    queryClient: ctx.queryClient,
    services,
    refreshSpectrumDecorations: ctx.refreshSpectrumDecorations,
  });

  const speedSource = createSpeedSourceFeature({
    panel: panels.settings.speedSource,
    settings: state.settings,
    queryClient: ctx.queryClient,
    services,
    formatting: {
      fmt: formatting.fmt,
    },
    getSpeedUnit: () => state.shell.speedUnit.value,
    activeViewId: ctx.activeViewId,
    activeSettingsTabId: panels.settingsShell.activeTabId,
  });

  const cars = createCarsFeature({
    settings: state.settings,
    queryClient: ctx.queryClient,
    panel: panels.settings.cars,
    analysisPanel: panels.settings.analysis,
    activeViewId: ctx.activeViewId,
    activeSettingsTabId: panels.settingsShell.activeTabId,
    openAnalysisTab: () => panels.settingsShell.activateTab("analysisTab"),
    refreshSpectrumDecorations: ctx.refreshSpectrumDecorations,
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
    activeViewId: ctx.activeViewId,
    activeSettingsTabId: panels.settingsShell.activeTabId,
    services,
    queryClient: ctx.queryClient,
  });

  const espFlash = createEspFlashFeature({
    panel: panels.settings.espFlash,
    activeViewId: ctx.activeViewId,
    activeSettingsTabId: panels.settingsShell.activeTabId,
    services,
    queryClient: ctx.queryClient,
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

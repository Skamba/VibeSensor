import { createCarsFeature, type CarsFeature } from "./features/cars_feature";
import { createEspFlashFeature } from "./features/esp_flash_feature";
import { createHistoryFeature, type HistoryFeature } from "./features/history_feature";
import { createSettingsFeature, type SettingsFeature } from "./features/settings_feature";
import { createUpdateFeature } from "./features/update_feature";
import type { AppFeatureBundleDeps } from "./app_feature_bundle";

export interface AppFeatureSecondaryBundle {
  dispose(): void;
  history: Pick<HistoryFeature, "refreshHistory">;
  openCarWizard(): void;
  settings: Pick<
    SettingsFeature,
    | "loadAnalysisSettingsFromServer"
    | "loadCarsFromServer"
    | "loadSpeedSourceFromServer"
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

  let carsFeature: CarsFeature | null = null;
  const settings = createSettingsFeature({
    state: {
      settings: state.settings,
      shell: state.shell,
    },
    panels: {
      settingsShell: panels.settingsShell,
      analysisPanel: panels.settings.analysis,
      carsPanel: panels.settings.cars.list,
      speedSourcePanel: panels.settings.speedSource,
    },
    ports: {
      openCarWizard: () => {
        carsFeature?.openWizard();
      },
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
    panel: panels.settings.cars.wizard,
    services: {
      t: services.t,
    },
    formatting: {
      fmt: formatting.fmt,
    },
    queryClient: serverState.queryClient,
    addCarFromWizard: (name, carType, aspects, orderReferenceStatus, variant) =>
      settings.addCarFromWizard(
        name,
        carType,
        aspects,
        orderReferenceStatus,
        variant,
      ),
  });
  carsFeature = cars;

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

  settings.bindHandlers();
  cars.bindWizardHandlers();
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
      cars.openWizard();
    },
    settings: {
      loadSpeedSourceFromServer: () => settings.loadSpeedSourceFromServer(),
      loadAnalysisSettingsFromServer: () => settings.loadAnalysisSettingsFromServer(),
      loadCarsFromServer: () => settings.loadCarsFromServer(),
    },
  };
}

import type { UiStartupFeaturePorts } from "./runtime/ui_startup_feature_ports";
import type { CarsFeature } from "./features/cars_feature";
import type { EspFlashFeature } from "./features/esp_flash_feature";
import type { HistoryFeature } from "./features/history_feature";
import type { RealtimeFeature, RealtimeFeatureRecordingPorts } from "./features/realtime_feature";
import type { SettingsFeature } from "./features/settings_feature";
import type { UpdateFeature } from "./features/update_feature";

export interface AppShellFeatureBindings {
  bindHandlers(): void;
}

export interface AppFeatureBundle {
  shell: AppShellFeatureBindings;
  startup: UiStartupFeaturePorts;
}

interface AppFeatureBundlePortSources {
  history: Pick<HistoryFeature, "bindHandlers" | "refreshHistory">;
  realtime: Pick<
    RealtimeFeature,
    | "bindHandlers"
    | "refreshLocationOptions"
    | "refreshLoggingStatus"
  >;
  settings: Pick<
    SettingsFeature,
    | "bindHandlers"
    | "syncSettingsInputs"
    | "loadSpeedSourceFromServer"
    | "loadAnalysisSettingsFromServer"
    | "loadCarsFromServer"
  >;
  cars: Pick<CarsFeature, "bindWizardHandlers">;
  update: Pick<UpdateFeature, "bindUpdateHandlers">;
  espFlash: Pick<EspFlashFeature, "bindHandlers">;
}

export function createRealtimeFeatureRecordingPorts(
  history: Pick<HistoryFeature, "refreshHistory">,
): RealtimeFeatureRecordingPorts {
  return {
    onRecordingStatusChanged: () => history.refreshHistory(),
  };
}

export function createAppFeatureBundlePorts(
  features: AppFeatureBundlePortSources,
): AppFeatureBundle {
  return {
    shell: {
      bindHandlers: () => {
        features.settings.bindHandlers();
        features.cars.bindWizardHandlers();
        features.realtime.bindHandlers();
        features.history.bindHandlers();
        features.update.bindUpdateHandlers();
        features.espFlash.bindHandlers();
      },
    },
    startup: {
      history: {
        refreshHistory: () => features.history.refreshHistory(),
      },
      realtime: {
        refreshLocationOptions: () => features.realtime.refreshLocationOptions(),
        refreshLoggingStatus: () => features.realtime.refreshLoggingStatus(),
      },
      settings: {
        loadSpeedSourceFromServer: () => features.settings.loadSpeedSourceFromServer(),
        loadAnalysisSettingsFromServer: () =>
          features.settings.loadAnalysisSettingsFromServer(),
        loadCarsFromServer: () => features.settings.loadCarsFromServer(),
      },
    },
  };
}

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
  dispose(): void;
  shell: AppShellFeatureBindings;
  startup: UiStartupFeaturePorts;
}

interface AppFeatureBundlePortSources {
  history: Pick<HistoryFeature, "bindHandlers" | "dispose" | "refreshHistory">;
  realtime: Pick<
    RealtimeFeature,
    | "bindHandlers"
    | "dispose"
    | "refreshLocationOptions"
    | "refreshLoggingStatus"
  >;
  settings: Pick<
    SettingsFeature,
    | "bindHandlers"
    | "dispose"
    | "syncSettingsInputs"
    | "loadSpeedSourceFromServer"
    | "loadAnalysisSettingsFromServer"
    | "loadCarsFromServer"
  >;
  cars: Pick<CarsFeature, "bindWizardHandlers" | "dispose">;
  update: Pick<UpdateFeature, "bindUpdateHandlers" | "dispose">;
  espFlash: Pick<EspFlashFeature, "bindHandlers" | "dispose">;
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
    dispose: () => {
      features.espFlash.dispose();
      features.update.dispose();
      features.history.dispose();
      features.realtime.dispose();
      features.settings.dispose();
      features.cars.dispose();
    },
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

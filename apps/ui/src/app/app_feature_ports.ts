import type { CarsFeature } from "./features/cars_feature";
import type { EspFlashFeature } from "./features/esp_flash_feature";
import type { HistoryFeature } from "./features/history_feature";
import type {
  RealtimeFeature,
  RealtimeFeatureRecordingPorts,
} from "./features/realtime_feature";
import type {
  SettingsFeature,
  SettingsFeatureRealtimePorts,
} from "./features/settings_feature";
import type { UpdateFeature } from "./features/update_feature";
import { createUiRecordingHistoryRefresh } from "./runtime/ui_recording_history_refresh";
import type { UiShellFeaturePorts } from "./runtime/ui_shell_feature_ports";
import type { UiStartupFeaturePorts } from "./runtime/ui_startup_feature_ports";

export interface AppFeatureBundle {
  shell: UiShellFeaturePorts;
  startup: UiStartupFeaturePorts;
}

export interface AppFeaturesForPorts {
  history: Pick<
    HistoryFeature,
    "bindHandlers" | "renderHistoryTable" | "reloadExpandedRunOnLanguageChange" | "refreshHistory"
  >;
  realtime: Pick<
    RealtimeFeature,
    | "bindHandlers"
    | "maybeRenderSensorsSettingsList"
    | "renderLoggingStatus"
    | "renderStatus"
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
    | "startGpsStatusPolling"
  >;
  cars: Pick<CarsFeature, "bindWizardHandlers">;
  update: Pick<UpdateFeature, "bindUpdateHandlers" | "startPolling">;
  espFlash: Pick<EspFlashFeature, "bindHandlers" | "startPolling">;
}

export function createSettingsFeatureRealtimePorts(
  realtime: Pick<RealtimeFeature, "renderStatus" | "renderLoggingStatus">,
): SettingsFeatureRealtimePorts {
  return {
    renderRealtimeStatus: () => realtime.renderStatus(),
    renderRealtimeLoggingStatus: () => realtime.renderLoggingStatus(),
  };
}

export function createRealtimeFeatureRecordingPorts(
  history: Pick<HistoryFeature, "refreshHistory">,
): RealtimeFeatureRecordingPorts {
  const refresh = createUiRecordingHistoryRefresh({
    refreshHistory: () => history.refreshHistory(),
  });
  return {
    onRecordingStatusChanged: () => refresh.onRecordingStatusChanged(),
  };
}

export function createAppFeaturePorts(features: AppFeaturesForPorts): AppFeatureBundle {
  return {
    shell: {
      bindSettingsHandlers: () => features.settings.bindHandlers(),
      bindCarWizardHandlers: () => features.cars.bindWizardHandlers(),
      bindRealtimeHandlers: () => features.realtime.bindHandlers(),
      bindHistoryHandlers: () => features.history.bindHandlers(),
      bindUpdateHandlers: () => features.update.bindUpdateHandlers(),
      bindEspFlashHandlers: () => features.espFlash.bindHandlers(),
      languageRefresh: {
        realtime: {
          maybeRenderSensorsSettingsList: (force) => features.realtime.maybeRenderSensorsSettingsList(force),
          renderLoggingStatus: () => features.realtime.renderLoggingStatus(),
          renderStatus: () => features.realtime.renderStatus(),
        },
        history: {
          renderHistoryTable: () => features.history.renderHistoryTable(),
          reloadExpandedRunOnLanguageChange: () => features.history.reloadExpandedRunOnLanguageChange(),
        },
        settings: {
          syncSettingsInputs: () => features.settings.syncSettingsInputs(),
        },
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
        loadAnalysisSettingsFromServer: () => features.settings.loadAnalysisSettingsFromServer(),
        loadCarsFromServer: () => features.settings.loadCarsFromServer(),
        startGpsStatusPolling: () => features.settings.startGpsStatusPolling(),
      },
      update: {
        startPolling: () => features.update.startPolling(),
      },
      espFlash: {
        startPolling: () => features.espFlash.startPolling(),
      },
    },
  };
}

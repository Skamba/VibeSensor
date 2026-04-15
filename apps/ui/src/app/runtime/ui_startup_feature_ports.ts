import type { EspFlashFeature } from "../features/esp_flash_feature";
import type { HistoryFeature } from "../features/history_feature";
import type { RealtimeFeature } from "../features/realtime_feature";
import type { SettingsFeature } from "../features/settings_feature";
import type { UpdateFeature } from "../features/update_feature";

export interface UiStartupFeaturePorts {
  history: Pick<HistoryFeature, "refreshHistory">;
  realtime: Pick<RealtimeFeature, "refreshLocationOptions" | "refreshLoggingStatus">;
  settings: Pick<
    SettingsFeature,
    | "loadSpeedSourceFromServer"
    | "loadAnalysisSettingsFromServer"
    | "loadCarsFromServer"
    | "startGpsStatusPolling"
  >;
  update: Pick<UpdateFeature, "startPolling">;
  espFlash: Pick<EspFlashFeature, "startPolling">;
}

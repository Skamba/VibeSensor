import type { SpeedSourceStatusPayload } from "../../api/types";
import type { SettingsState } from "../settings_state";
import { batch } from "../ui_signals";

export function applySpeedSourceStatusToSettings(
  settings: SettingsState["speed"],
  status: SpeedSourceStatusPayload,
): void {
  batch(() => {
    settings.gpsFallbackActive.value = status.fallback_active;
    settings.gpsEffectiveSpeedKph.value = status.effective_speed_kmh;
    settings.resolvedSource.value = status.speed_source;
  });
}

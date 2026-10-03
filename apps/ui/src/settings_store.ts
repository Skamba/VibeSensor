import { batch, computed, signal } from "@preact/signals";

import {
  getSettingsObdStatus,
  getSettingsSpeedSource,
  getSpeedSourceStatus,
} from "./api/settings";
import type {
  ObdStatusPayload,
  SpeedSourceKind,
  SpeedSourcePayload,
  SpeedSourceStatusPayload,
} from "./api/types";
import { activeView, isDemoMode, settingsTab } from "./app_store";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "./config";
import { poll } from "./poll";
import type { SpeedSourceSnapshot } from "./speed_source";

/** Saved settings shared across pages: the speed source and its live status. */

export const speedSettings = {
  source: signal<SpeedSourceKind>("gps"),
  manualSpeedKph: signal<number | null>(null),
  staleTimeoutS: signal<number | null>(null),
  obdDeviceMac: signal<string | null>(null),
  obdDeviceName: signal<string | null>(null),
  /** What the server reports is in use (for example a manual fallback). */
  resolvedSource: signal<SpeedSourceStatusPayload["speed_source"] | null>(null),
  gpsFallbackActive: signal(false),
  gpsEffectiveSpeedKph: signal<number | null>(null),
};

export const speedSourceSnapshot = computed<SpeedSourceSnapshot>(() => ({
  speedSource: speedSettings.source.value,
  manualSpeedKph: speedSettings.manualSpeedKph.value,
  resolvedSpeedSource: speedSettings.resolvedSource.value,
}));

export const speedStatus = signal<SpeedSourceStatusPayload | null>(null);
export const obdStatus = signal<ObdStatusPayload | null>(null);

export function applySpeedSource(
  payload: SpeedSourcePayload,
  options: { keepResolvedSource?: boolean } = {},
): void {
  batch(() => {
    speedSettings.source.value = payload.speed_source;
    speedSettings.manualSpeedKph.value = payload.manual_speed_kph;
    speedSettings.staleTimeoutS.value = payload.stale_timeout_s;
    speedSettings.obdDeviceMac.value = payload.obd_device_mac ?? null;
    speedSettings.obdDeviceName.value = payload.obd_device_name ?? null;
    if (!options.keepResolvedSource) {
      speedSettings.resolvedSource.value = null;
    }
  });
}

/** Loads the saved speed source without discarding the live resolved source. */
export async function loadSpeedSource(): Promise<void> {
  applySpeedSource(await getSettingsSpeedSource(), {
    keepResolvedSource: true,
  });
}

const speedTabVisible = computed(
  () =>
    activeView.value === "settingsView" &&
    settingsTab.value === "speedSourceTab",
);

// The dashboard readout and the speed page both follow the live status.
const statusPoll = poll({
  active: computed(
    () =>
      !isDemoMode() &&
      (activeView.value === "dashboardView" || speedTabVisible.value),
  ),
  intervalMs: (last) =>
    last?.status.connection_state === "connected"
      ? GPS_POLL_FAST_MS
      : GPS_POLL_SLOW_MS,
  load: async () => {
    const wantObd =
      speedTabVisible.peek() &&
      (speedSettings.source.peek() === "obd2" ||
        speedSettings.obdDeviceMac.peek() != null);
    const [status, obd] = await Promise.all([
      getSpeedSourceStatus(),
      wantObd ? getSettingsObdStatus() : Promise.resolve(null),
    ]);
    return { status, obd };
  },
  onData: ({ status, obd }) => {
    batch(() => {
      speedStatus.value = status;
      obdStatus.value = obd;
      speedSettings.gpsFallbackActive.value = status.fallback_active;
      speedSettings.gpsEffectiveSpeedKph.value = status.effective_speed_kmh;
      speedSettings.resolvedSource.value = status.speed_source;
    });
  },
});

export function refreshSpeedStatus(): Promise<void> {
  return statusPoll.refresh();
}

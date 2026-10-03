import { batch, computed, signal } from "@preact/signals";

import {
  getSettingsObdStatus,
  getSettingsSpeedSource,
  getSpeedSourceStatus,
} from "./api/settings";
import type {
  CarRecord,
  ObdStatusPayload,
  SpeedSourceKind,
  SpeedSourcePayload,
  SpeedSourceStatusPayload,
} from "./api/types";
import { activeView, isDemoMode, settingsTab } from "./app_store";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "./config";
import { poll } from "./poll";
import { type CarSelectionState, deriveCarSelection } from "./car_selection";
import type { SpeedSourceSnapshot } from "./speed_source";
import {
  type AnalysisTuningSettings,
  type CarAspectSettings,
  defaultAnalysisTuningSettings,
  defaultCarAspectSettings,
} from "./vehicle_settings";

/**
 * Saved settings shared across pages: cars and the active car, the analysis
 * tuning, the speed source, and the live speed status.
 */

export const carSettings = {
  cars: signal<CarRecord[]>([]),
  activeCarId: signal<string | null>(null),
  carsLoaded: signal(false),
  /** The active car's aspects, used for live order context. */
  activeVehicleSettings: signal<CarAspectSettings>({
    ...defaultCarAspectSettings,
  }),
};

export const carSelection = computed<CarSelectionState>(() =>
  deriveCarSelection(
    carSettings.cars.value,
    carSettings.activeCarId.value,
    carSettings.carsLoaded.value,
  ),
);

export const activeCar = computed(() =>
  carSelection.value.kind === "active" ? carSelection.value.car : null,
);

export const analysisTuning = signal<AnalysisTuningSettings>({
  ...defaultAnalysisTuningSettings,
});

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

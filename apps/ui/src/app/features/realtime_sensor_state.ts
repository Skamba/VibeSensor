import type { LocationOption, LoggingStatusPayload } from "../../api/types";
import type { AdaptedClient } from "../../transport/live_models";
import * as I18N from "../../i18n";
import {
  createCarSelectionDerivedState,
  type CarSelectionState,
} from "../car_selection_state";
import type { RealtimeState } from "../realtime_state";
import type { SettingsState } from "../settings_state";
import type { ShellState } from "../shell_state";
import type { SpectrumState } from "../spectrum_state";
import { computed, type ReadonlySignal } from "../ui_signals";

export type ActiveCarDisplayState = {
  text: string;
  isWarning: boolean;
};

export type LiveHealth = {
  variant: "muted" | "ok" | "warn" | "bad";
  text: string;
  summary: string;
  showOverviewPill: boolean;
};

type CaptureReadinessPayload = NonNullable<
  LoggingStatusPayload["capture_readiness"]
>;

export interface RealtimeSensorStateDeps {
  realtime: RealtimeState;
  settings: SettingsState;
  shell: Pick<ShellState, "lang">;
  spectrum: SpectrumState;
  captureReadinessSummaryText: (
    readiness: CaptureReadinessPayload | null,
  ) => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
  formatInt: (value: number) => string;
}

export interface RealtimeSensorState {
  activeCarSelection: ReadonlySignal<CarSelectionState>;
  activeCarDisplayState: ReadonlySignal<ActiveCarDisplayState>;
  assignedClientCount: ReadonlySignal<number>;
  connectedClients: ReadonlySignal<AdaptedClient[]>;
  hasActiveCarSelection: ReadonlySignal<boolean>;
  liveHealth: ReadonlySignal<LiveHealth>;
  locationCodeForClient(client: AdaptedClient): string;
  locationOptions: ReadonlySignal<LocationOption[]>;
  strongestSignal: ReadonlySignal<{ client: AdaptedClient; db: number } | null>;
  strongestSignalText: ReadonlySignal<string>;
}

const SHORTHAND_LOCATION_MAP: Record<string, string> = {
  "front left": "front_left_wheel",
  "front right": "front_right_wheel",
  "rear left": "rear_left_wheel",
  "rear right": "rear_right_wheel",
  driver: "driver_seat",
};

export function createRealtimeSensorState(
  ctx: RealtimeSensorStateDeps,
): RealtimeSensorState {
  const { realtime, settings, shell, spectrum, t, formatInt } = ctx;
  const carSelection = createCarSelectionDerivedState(settings.car);

  function locationLabelForLang(lang: string, code: string): string {
    return I18N.get(lang, `location.${code}`, { code });
  }

  function locationLabel(code: string): string {
    return locationLabelForLang(shell.lang.value, code);
  }

  function buildLocationOptions(codes: readonly string[]): LocationOption[] {
    return codes.map((code) => ({ code, label: locationLabel(code) }));
  }

  const locationOptions = computed<LocationOption[]>(() => {
    return buildLocationOptions(realtime.locationCodes.value);
  });

  function locationCodeForClient(client: AdaptedClient): string {
    const explicitCode = String(client.location_code || "").trim();
    if (explicitCode && realtime.locationCodes.value.includes(explicitCode))
      return explicitCode;
    const name = String(client.name || "").trim();
    if (!name) return "";
    const normalizedName = name
      .toLowerCase()
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    for (const [token, code] of Object.entries(SHORTHAND_LOCATION_MAP)) {
      if (
        normalizedName.includes(token) &&
        realtime.locationCodes.value.includes(code)
      )
        return code;
    }
    for (const code of realtime.locationCodes.value) {
      const labels = I18N.getForAllLangs(`location.${code}`);
      if (labels.some((label) => label === name)) return code;
    }
    const match = locationOptions.value.find((loc) => loc.label === name);
    return match ? match.code : "";
  }

  function clientDisplayName(client: AdaptedClient): string {
    return String(client.name || "").trim() || client.id;
  }

  function clientLocationText(client: AdaptedClient): string {
    const code = locationCodeForClient(client);
    if (!code) {
      return t("dashboard.sensor_unassigned");
    }
    const option = locationOptions.value.find(
      (location) => location.code === code,
    );
    return option?.label ?? locationLabel(code);
  }

  const connectedClients = computed<AdaptedClient[]>(() => {
    return realtime.clients.value.filter((client) => Boolean(client.connected));
  });

  const assignedClientCount = computed(() => {
    return realtime.clients.value.filter((client) =>
      locationCodeForClient(client),
    ).length;
  });

  const strongestSignal = computed<{
    client: AdaptedClient;
    db: number;
  } | null>(() => {
    let bestClient: AdaptedClient | null = null;
    let bestDb = Number.NEGATIVE_INFINITY;
    for (const client of connectedClients.value) {
      const db =
        spectrum.spectra.value.clients[client.id]?.strength_metrics
          ?.vibration_strength_db;
      if (typeof db !== "number" || !Number.isFinite(db)) continue;
      if (db > bestDb) {
        bestDb = db;
        bestClient = client;
      }
    }
    if (!bestClient) {
      return null;
    }
    return {
      client: bestClient,
      db: bestDb,
    };
  });

  const strongestSignalText = computed(() => {
    const signal = strongestSignal.value;
    if (!signal) {
      return t("dashboard.strongest_signal_none");
    }
    const primary = locationCodeForClient(signal.client)
      ? clientLocationText(signal.client)
      : clientDisplayName(signal.client);
    return `${primary} · ${formatInt(signal.db)} dB`;
  });

  const activeCarDisplayState = computed<ActiveCarDisplayState>(() => {
    const selection = carSelection.selection.value;
    if (selection.kind === "loading") {
      return {
        text: t("dashboard.active_car_loading"),
        isWarning: false,
      };
    }
    if (selection.kind !== "active") {
      return {
        text:
          selection.kind === "no_cars"
            ? t("dashboard.active_car_none_no_cars")
            : t("dashboard.active_car_none_blocked"),
        isWarning: true,
      };
    }
    return {
      text: selection.car.name,
      isWarning: false,
    };
  });

  const hasActiveCarSelection = computed(
    () => carSelection.hasResolvedActiveCar.value,
  );

  const liveHealth = computed<LiveHealth>(() => {
    const loggingStatus = realtime.loggingStatus.value;
    if (loggingStatus.write_error) {
      return {
        variant: "bad",
        text: t("dashboard.health.write_error"),
        summary: loggingStatus.write_error,
        showOverviewPill: true,
      };
    }
    const connected = connectedClients.value;
    if (!connected.length) {
      return {
        variant: "muted",
        text: t("dashboard.health.no_signal"),
        summary: t("dashboard.logging.waiting"),
        showOverviewPill: true,
      };
    }
    if (!hasActiveCarSelection.value) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.active_car_required"),
        showOverviewPill: true,
      };
    }
    const droppedCount = connected.filter(
      (client) => (client.dropped_frames ?? 0) > 0,
    ).length;
    if (droppedCount > 0) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.frame_loss", {
          count: formatInt(droppedCount),
        }),
        showOverviewPill: true,
      };
    }
    const unassignedConnectedCount = connected.filter(
      (client) => !locationCodeForClient(client),
    ).length;
    if (unassignedConnectedCount > 0) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.unassigned", {
          count: formatInt(unassignedConnectedCount),
        }),
        showOverviewPill: true,
      };
    }
    const offlineCount = realtime.clients.value.filter(
      (client) => !client.connected,
    ).length;
    if (offlineCount > 0) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: t("dashboard.logging.offline", {
          count: formatInt(offlineCount),
        }),
        showOverviewPill: true,
      };
    }
    const connectedCount = formatInt(connected.length);
    const assignedCount = formatInt(assignedClientCount.value);
    if (loggingStatus.enabled) {
      return {
        variant: "ok",
        text: t("dashboard.health.recording"),
        summary: t("dashboard.logging.running", {
          connected: connectedCount,
          assigned: assignedCount,
        }),
        showOverviewPill: false,
      };
    }
    const captureReadiness = loggingStatus.capture_readiness ?? null;
    if (captureReadiness && !captureReadiness.is_ready) {
      return {
        variant: "warn",
        text: t("dashboard.health.attention"),
        summary: ctx.captureReadinessSummaryText(captureReadiness),
        showOverviewPill: true,
      };
    }
    return {
      variant: "ok",
      text: t("dashboard.health.ready"),
      summary: "",
      showOverviewPill: false,
    };
  });

  return {
    activeCarDisplayState,
    activeCarSelection: carSelection.selection,
    assignedClientCount,
    connectedClients,
    hasActiveCarSelection,
    liveHealth,
    locationCodeForClient,
    locationOptions,
    strongestSignal,
    strongestSignalText,
  };
}

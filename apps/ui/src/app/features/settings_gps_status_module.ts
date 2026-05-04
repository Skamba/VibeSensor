import type { QueryClient } from "@tanstack/query-core";

import { getSettingsObdStatus, getSpeedSourceStatus } from "../../api";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "../../config";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { SettingsState } from "../settings_state";
import { batch, computed, signal, type ReadonlySignal } from "../ui_signals";
import { DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL } from "../views/speed_source_panel_defaults";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";
import {
  buildSpeedSourceDiagnosticsRenderModel,
  type SettingsSpeedSourcePresenterDeps,
} from "../views/settings_speed_source_presenter";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";
import { applySpeedSourceStatusToSettings } from "./speed_source_status_state";

interface SettingsGpsStatusModulePorts {
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  syncSpeedSourceSelectionUi: () => void;
}

export interface SettingsGpsStatusModuleDeps {
  panel: SpeedSourcePanelView;
  settings: SettingsState;
  queryClient: QueryClient;
  services: Pick<FeatureServices, "t">;
  formatting: Pick<FeatureFormatting, "fmt">;
  getSpeedUnit: () => string;
  ports: SettingsGpsStatusModulePorts;
}

interface GpsStatusSnapshot {
  obdStatus: Awaited<ReturnType<typeof getSettingsObdStatus>> | null;
  status: Awaited<ReturnType<typeof getSpeedSourceStatus>>;
}

export interface SettingsGpsStatusModule {
  bindHandlers(): void;
  dispose(): void;
  markStartupReady(): Promise<void>;
}

export function createSettingsGpsStatusModule(
  ctx: SettingsGpsStatusModuleDeps,
): SettingsGpsStatusModule {
  const { panel, settings } = ctx;
  const handlersBound = signal(false);
  const startupReady = signal(false);
  const presenterDeps: SettingsSpeedSourcePresenterDeps = {
    fmt: ctx.formatting.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t: ctx.services.t,
  };
  const diagnosticsModel = signal(DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL);
  panel.diagnostics.value = diagnosticsModel;
  const pollingEnabled = computed(
    () =>
      handlersBound.value &&
      startupReady.value &&
      ctx.ports.activeViewId.value === "settingsView" &&
      ctx.ports.activeSettingsTabId.value === "speedSourceTab",
  );

  const gpsStatusQuery = createObservedServerStateQuery<GpsStatusSnapshot>({
    enabled: pollingEnabled,
    observerOptions: createHiddenTabPollingObserverOptions<GpsStatusSnapshot>(
      (query) =>
        query.state.data?.status.connection_state === "connected"
          ? GPS_POLL_FAST_MS
          : GPS_POLL_SLOW_MS,
    ),
    onData: ({ status, obdStatus }) => {
      batch(() => {
        applySpeedSourceStatusToSettings(settings.speed, status);
        diagnosticsModel.value = buildSpeedSourceDiagnosticsRenderModel(
          status,
          obdStatus,
          presenterDeps,
        );
      });
      ctx.ports.syncSpeedSourceSelectionUi();
    },
    queryClient: ctx.queryClient,
    queryFn: async () => {
      const shouldLoadObdStatus =
        settings.speed.source.value === "obd2" ||
        settings.speed.obdDeviceMac.value != null;
      const [status, obdStatus] = await Promise.all([
        getSpeedSourceStatus(),
        shouldLoadObdStatus ? getSettingsObdStatus() : Promise.resolve(null),
      ]);
      return {
        obdStatus,
        status,
      };
    },
    queryKey: serverStateQueryKeys.settings.gpsStatus(),
  });

  return {
    bindHandlers(): void {
      handlersBound.value = true;
    },
    dispose(): void {
      gpsStatusQuery.dispose();
    },
    markStartupReady(): Promise<void> {
      startupReady.value = true;
      return gpsStatusQuery
        .fetch()
        .then(() => undefined)
        .catch(() => undefined);
    },
  };
}

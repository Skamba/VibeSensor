import type { QueryClient } from "@tanstack/query-core";

import { getSpeedSourceStatus } from "../../api";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "../../config";
import type { SettingsState } from "../ui_app_state";
import { computed, signal, type ReadonlySignal } from "../ui_signals";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { applySpeedSourceStatusToSettings } from "./speed_source_status_state";

const DASHBOARD_SPEED_STATUS_QUERY_KEY = [
  "settings",
  "dashboard-gps-status",
] as const;

interface DashboardGpsStatusSnapshot {
  obdStatus: null;
  status: Awaited<ReturnType<typeof getSpeedSourceStatus>>;
}

interface DashboardSpeedSourceStatusModuleDeps {
  activeViewId: ReadonlySignal<string>;
  queryClient: QueryClient;
  settings: SettingsState;
}

export interface DashboardSpeedSourceStatusModule {
  bindHandlers(): void;
  dispose(): void;
  markStartupReady(): Promise<void>;
}

export function createDashboardSpeedSourceStatusModule(
  deps: DashboardSpeedSourceStatusModuleDeps,
): DashboardSpeedSourceStatusModule {
  const handlersBound = signal(false);
  const startupReady = signal(false);
  const pollingEnabled = computed(
    () =>
      handlersBound.value &&
      startupReady.value &&
      deps.activeViewId.value === "dashboardView",
  );

  const gpsStatusQuery = createObservedServerStateQuery({
    enabled: pollingEnabled,
    observerOptions: createHiddenTabPollingObserverOptions<
      DashboardGpsStatusSnapshot,
      typeof DASHBOARD_SPEED_STATUS_QUERY_KEY
    >((query) =>
      query.state.data?.status.connection_state === "connected"
        ? GPS_POLL_FAST_MS
        : GPS_POLL_SLOW_MS,
    ),
    onData: ({ status }) => {
      applySpeedSourceStatusToSettings(deps.settings.speed, status);
    },
    queryClient: deps.queryClient,
    queryFn: async (): Promise<DashboardGpsStatusSnapshot> => ({
      obdStatus: null,
      status: await getSpeedSourceStatus(),
    }),
    queryKey: DASHBOARD_SPEED_STATUS_QUERY_KEY,
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

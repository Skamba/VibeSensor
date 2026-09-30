import type { QueryClient } from "@tanstack/query-core";

import {
  getClientLocations,
  identifyClient as identifyClientApi,
  removeClient as removeClientApi,
  setClientLocation as setClientLocationApi,
} from "../../api/clients";
import {
  getLoggingStatus,
  startLoggingRun,
  stopLoggingRun,
} from "../../api/logging";
import type { LoggingStatusPayload } from "../../api/types";
import { defaultLocationCodes } from "../../constants";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import {
  syncSelectedRealtimeClient,
  type RealtimeState,
} from "../realtime_state";
import type { SettingsState } from "../settings_state";
import type { ShellState } from "../shell_state";
import type { SpectrumState } from "../spectrum_state";
import {
  batch,
  computed,
  effect,
  effectOnChange,
  signal,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";
import type { RealtimeLiveOverviewBridge } from "../views/realtime_live_overview";
import type { RealtimeLoggingPanelBridge } from "../views/realtime_logging_panel";
import type { RealtimeLoggingPendingAction } from "../views/realtime_logging_view_models";
import type { SensorsPanelView } from "../views/sensors_panel";
import { createRealtimeFeatureViewState } from "./realtime_feature_view_state";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";

export interface RealtimeLoggingError {
  kind: "error" | "unavailable";
  message: string;
}

/** Controller-owned logging state the derived realtime view models read. */
export interface RealtimeLoggingSignals {
  readonly handlersBound: ReadonlySignal<boolean>;
  readonly pendingLoggingAction: ReadonlySignal<RealtimeLoggingPendingAction>;
  readonly loggingError: ReadonlySignal<RealtimeLoggingError | null>;
}

export interface RealtimeFeature {
  readonly signals: RealtimeLoggingSignals;
  bindHandlers(): void;
  dispose(): void;
  refreshLoggingStatus(): Promise<void>;
  startLogging(): Promise<void>;
  stopLogging(): Promise<void>;
  refreshLocationOptions(): Promise<void>;
  setClientLocation(clientId: string, locationCode: string): Promise<void>;
  identifyClient(clientId: string): Promise<void>;
  removeClient(clientId: string): Promise<void>;
}

const LOGGING_STATUS_IDLE_POLL_MS = 2_000;
const LOGGING_STATUS_ACTIVE_POLL_MS = 2_000;

function didHistoryAffectingStatusChange(
  previous: LoggingStatusPayload,
  next: LoggingStatusPayload,
): boolean {
  return (
    previous.enabled !== next.enabled ||
    previous.run_id !== next.run_id ||
    previous.analysis_in_progress !== next.analysis_in_progress ||
    previous.last_completed_run_id !== next.last_completed_run_id ||
    previous.last_completed_run_error !== next.last_completed_run_error
  );
}

/**
 * Realtime controller: logging-status polling and start/stop, idle capture
 * readiness refreshes, client location/identify/remove actions, and the
 * dashboard/sensors panel bindings fed by the derived realtime view state.
 */
export function createRealtimeFeature(ctx: {
  realtime: RealtimeState;
  settings: SettingsState;
  spectrum: SpectrumState;
  shell: Pick<ShellState, "lang">;
  sensorsPanel: SensorsPanelView;
  liveOverview: RealtimeLiveOverviewBridge;
  loggingPanel: RealtimeLoggingPanelBridge;
  setShellLiveStatus: (variant: string, text: string) => void;
  navigation: {
    activatePrimaryView(viewId: string): void;
    activateSettingsTab(tabId: string): void;
    openCarWizard(): void;
  };
  sendSelection: () => void;
  onRecordingStatusChanged: () => Promise<void>;
  queryClient: QueryClient;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "formatInt">;
}): RealtimeFeature {
  const { realtime, navigation } = ctx;
  const { t, showError } = ctx.services;
  const isDemoMode = new URLSearchParams(window.location.search).has("demo");
  const state = {
    handlersBound: signal(false),
    pendingLoggingAction: signal<RealtimeLoggingPendingAction>(null),
    loggingError: signal<RealtimeLoggingError | null>(null),
  };
  const viewState = createRealtimeFeatureViewState({
    state: {
      realtime,
      settings: ctx.settings,
      shell: ctx.shell,
      spectrum: ctx.spectrum,
    },
    services: { t },
    formatting: { formatInt: ctx.formatting.formatInt },
    workflow: state,
  });
  ctx.liveOverview.model.value = viewState.liveOverviewModel;
  ctx.loggingPanel.model.value = viewState.loggingPanelModel;
  ctx.sensorsPanel.model.value = viewState.sensorsPanelModel;
  const idleCaptureReadinessSignature = viewState.idleCaptureReadinessSignature;

  let idleCaptureReadinessRefreshInFlight = false;
  let lastIdleCaptureReadinessSignature: string | null = null;
  let queuedIdleCaptureReadinessSignature: string | null = null;
  const idleCaptureReadinessTrigger = computed(() =>
    [
      idleCaptureReadinessSignature.value,
      state.handlersBound.value ? "1" : "0",
      state.pendingLoggingAction.value ?? "",
      realtime.loggingStatus.value.enabled ? "1" : "0",
      realtime.loggingStatus.value.analysis_in_progress ? "1" : "0",
      realtime.loggingStatus.value.last_completed_run_id ? "1" : "0",
    ].join("::"),
  );

  function syncIdleCaptureReadinessSignature(): void {
    lastIdleCaptureReadinessSignature = idleCaptureReadinessSignature.peek();
    queuedIdleCaptureReadinessSignature = null;
  }

  function applyLocationCodes(codes: string[]): void {
    realtime.locationCodes.value = codes.length
      ? codes
      : defaultLocationCodes.slice();
  }

  async function refreshIdleCaptureReadiness(signature: string): Promise<void> {
    const handlersBound = state.handlersBound.peek();
    const pendingLoggingAction = state.pendingLoggingAction.peek();
    if (!handlersBound || isDemoMode || pendingLoggingAction !== null) {
      return;
    }
    const loggingStatus = realtime.loggingStatus.peek();
    if (
      loggingStatus.enabled ||
      loggingStatus.analysis_in_progress ||
      Boolean(loggingStatus.last_completed_run_id)
    ) {
      return;
    }
    if (lastIdleCaptureReadinessSignature === signature) {
      return;
    }
    if (idleCaptureReadinessRefreshInFlight) {
      queuedIdleCaptureReadinessSignature = signature;
      return;
    }
    lastIdleCaptureReadinessSignature = signature;
    idleCaptureReadinessRefreshInFlight = true;
    await refreshLoggingStatus();
    idleCaptureReadinessRefreshInFlight = false;
    const queuedSignature = queuedIdleCaptureReadinessSignature;
    queuedIdleCaptureReadinessSignature = null;
    if (
      queuedSignature !== null &&
      queuedSignature !== lastIdleCaptureReadinessSignature
    ) {
      await refreshIdleCaptureReadiness(queuedSignature);
    }
  }

  const disposeIdleCaptureReadinessSync = effectOnChange(
    idleCaptureReadinessTrigger,
    () => {
      void refreshIdleCaptureReadiness(idleCaptureReadinessSignature.peek());
    },
  );

  function handleLoggingStatusData(nextStatus: LoggingStatusPayload): void {
    const previousStatus = realtime.loggingStatus.peek();
    realtime.loggingStatus.value = nextStatus;
    state.loggingError.value = null;
    if (!didHistoryAffectingStatusChange(previousStatus, nextStatus)) {
      return;
    }
    void ctx.onRecordingStatusChanged().catch((err) => {
      const message =
        err instanceof Error ? err.message : t("status.unavailable");
      showError(message || t("status.unavailable"));
    });
  }

  const loggingStatusPollingEnabled = computed(
    () => state.handlersBound.value && !isDemoMode,
  );

  const loggingStatusQuery =
    createObservedServerStateQuery<LoggingStatusPayload>({
      enabled: loggingStatusPollingEnabled,
      observerOptions:
        createHiddenTabPollingObserverOptions<LoggingStatusPayload>((query) => {
          const nextStatus = query.state.data;
          return nextStatus?.enabled || nextStatus?.analysis_in_progress
            ? LOGGING_STATUS_ACTIVE_POLL_MS
            : LOGGING_STATUS_IDLE_POLL_MS;
        }),
      onData: handleLoggingStatusData,
      onError: () => {
        batch(() => {
          state.pendingLoggingAction.value = null;
          state.loggingError.value = {
            kind: "unavailable",
            message: t("status.unavailable"),
          };
        });
      },
      queryClient: ctx.queryClient,
      queryFn: async () => {
        syncIdleCaptureReadinessSignature();
        if (isDemoMode && state.pendingLoggingAction.peek() === null) {
          state.loggingError.value = null;
          return realtime.loggingStatus.peek();
        }
        return getLoggingStatus();
      },
      queryKey: serverStateQueryKeys.realtime.loggingStatus(),
    });

  function openSettingsView(tabId: string): void {
    navigation.activatePrimaryView("settingsView");
    navigation.activateSettingsTab(tabId);
  }

  const disposeLiveStatusSync = effect(() => {
    const model = viewState.liveOverviewModel.value;
    untracked(() => {
      ctx.setShellLiveStatus(model.runHealth.variant, model.runHealth.text);
    });
  });

  function bindHandlers(): void {
    if (state.handlersBound.peek()) {
      return;
    }
    ctx.loggingPanel.actions.value = {
      onStartLogging: () => {
        void startLogging();
      },
      onStopLogging: () => {
        void stopLogging();
      },
      onSummaryAction: (action) => {
        if (action === "open-history") {
          navigation.activatePrimaryView("historyView");
          return;
        }
        if (action === "open-add-car") {
          openSettingsView("carTab");
          navigation.openCarWizard();
          return;
        }
        if (action === "open-cars") {
          openSettingsView("carTab");
          return;
        }
        if (action === "open-sensors") {
          openSettingsView("sensorsTab");
          return;
        }
        openSettingsView("speedSourceTab");
      },
    };
    state.handlersBound.value = true;
    ctx.sensorsPanel.actions.value = {
      onSensorLocationChange: (change) => {
        void setClientLocation(change.clientId, change.locationCode);
      },
      onSensorTableAction: (action) => {
        if (action.type === "identify") {
          void identifyClient(action.clientId);
          return;
        }
        void removeClient(action.clientId);
      },
    };
  }

  async function refreshLoggingStatus(): Promise<void> {
    try {
      await loggingStatusQuery.fetch();
    } catch {
      return;
    }
  }

  async function startLogging(): Promise<void> {
    if (state.pendingLoggingAction.peek()) return;
    syncIdleCaptureReadinessSignature();
    batch(() => {
      state.pendingLoggingAction.value = "starting";
      state.loggingError.value = null;
    });
    try {
      realtime.loggingStatus.value = await startLoggingRun();
      await ctx.onRecordingStatusChanged();
      loggingStatusQuery.setData(() => realtime.loggingStatus.peek());
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      batch(() => {
        state.pendingLoggingAction.value = null;
        state.loggingError.value = {
          kind: "error",
          message: message || t("status.unavailable"),
        };
      });
      return;
    }
    batch(() => {
      state.pendingLoggingAction.value = null;
      state.loggingError.value = null;
    });
  }

  async function stopLogging(): Promise<void> {
    if (state.pendingLoggingAction.peek()) return;
    syncIdleCaptureReadinessSignature();
    batch(() => {
      state.pendingLoggingAction.value = "stopping";
      state.loggingError.value = null;
    });
    try {
      realtime.loggingStatus.value = await stopLoggingRun();
      await ctx.onRecordingStatusChanged();
      loggingStatusQuery.setData(() => realtime.loggingStatus.peek());
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      batch(() => {
        state.pendingLoggingAction.value = null;
        state.loggingError.value = {
          kind: "error",
          message: message || t("status.unavailable"),
        };
      });
      return;
    }
    batch(() => {
      state.pendingLoggingAction.value = null;
      state.loggingError.value = null;
    });
  }

  async function refreshLocationOptions(): Promise<void> {
    const payload = await ctx.queryClient.fetchQuery({
      queryFn: () => getClientLocations(),
      queryKey: serverStateQueryKeys.realtime.clientLocations(),
      staleTime: 0,
    });
    const codes = Array.isArray(payload.locations)
      ? payload.locations
          .map((row) => row.code)
          .filter((code): code is string => typeof code === "string")
      : [];
    applyLocationCodes(codes);
  }

  async function setClientLocation(
    clientId: string,
    locationCode: string,
  ): Promise<void> {
    if (!clientId) return;
    const clients = realtime.clients.peek();
    const existing = clients.find((client) => client.id === clientId);
    const existingLocationCode = String(existing?.location_code || "").trim();
    if (existing && existingLocationCode === locationCode) return;
    try {
      await setClientLocationApi(clientId, locationCode);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : t("actions.set_location_failed"),
      );
      return;
    }
    const nextClients = realtime.clients.peek();
    const client = nextClients.find((row) => row.id === clientId);
    if (client) {
      realtime.clients.value = nextClients.map((row) =>
        row.id === clientId ? { ...row, location_code: locationCode } : row,
      );
    }
  }

  async function identifyClient(clientId: string): Promise<void> {
    if (!clientId) return;
    await identifyClientApi(clientId);
  }

  async function removeClient(clientId: string): Promise<void> {
    if (!clientId) return;
    const confirmed = await ctx.services.requestConfirmation(
      t("actions.remove_client_confirm", { id: clientId }),
    );
    if (!confirmed) return;
    try {
      await removeClientApi(clientId);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : t("actions.remove_client_failed"),
      );
      return;
    }
    const previousSelectedClientId = realtime.selectedClientId.peek();
    realtime.clients.value = realtime.clients
      .peek()
      .filter((client) => client.id !== clientId);
    if (realtime.selectedClientId.peek() === clientId) {
      realtime.selectedClientId.value = null;
    }
    syncSelectedRealtimeClient(realtime);
    if (previousSelectedClientId !== realtime.selectedClientId.peek()) {
      ctx.sendSelection();
    }
  }

  return {
    dispose(): void {
      disposeLiveStatusSync();
      loggingStatusQuery.dispose();
      disposeIdleCaptureReadinessSync();
      viewState.dispose();
    },
    signals: state,
    bindHandlers,
    refreshLoggingStatus,
    startLogging,
    stopLogging,
    refreshLocationOptions,
    setClientLocation,
    identifyClient,
    removeClient,
  };
}

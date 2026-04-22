import type { QueryClient } from "@tanstack/query-core";

import {
  getClientLocations as getClientLocationsApi,
  identifyClient as identifyClientApi,
  removeClient as removeClientApi,
  setClientLocation as setClientLocationApi,
} from "../../api/clients";
import {
  getLoggingStatus as getLoggingStatusApi,
  startLoggingRun as startLoggingRunApi,
  stopLoggingRun as stopLoggingRunApi,
} from "../../api/logging";
import { defaultLocationCodes } from "../../constants";
import type {
  ClientLocationsResponse,
  LoggingStatusPayload,
} from "../../api/types";
import {
  syncSelectedRealtimeClient,
  type RealtimeState,
} from "../ui_app_state";
import {
  batch,
  computed,
  effectOnChange,
  signal,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";
import type { RealtimeLoggingPendingAction } from "../views/realtime_logging_view_models";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";

export interface RealtimeFeatureWorkflowApi {
  getLoggingStatus(): Promise<LoggingStatusPayload>;
  startLoggingRun(): Promise<LoggingStatusPayload>;
  stopLoggingRun(): Promise<LoggingStatusPayload>;
  getClientLocations(): Promise<ClientLocationsResponse>;
  setClientLocation(clientId: string, locationCode: string): Promise<void>;
  identifyClient(clientId: string): Promise<void>;
  removeClient(clientId: string): Promise<void>;
}

export interface RealtimeFeatureWorkflowLoggingError {
  kind: "error" | "unavailable";
  message: string;
}

export interface RealtimeFeatureWorkflowSignals {
  readonly handlersBound: ReadonlySignal<boolean>;
  readonly pendingLoggingAction: ReadonlySignal<RealtimeLoggingPendingAction>;
  readonly loggingError: ReadonlySignal<RealtimeFeatureWorkflowLoggingError | null>;
}

export interface RealtimeFeatureWorkflowState {
  readonly handlersBound: Signal<boolean>;
  readonly pendingLoggingAction: Signal<RealtimeLoggingPendingAction>;
  readonly loggingError: Signal<RealtimeFeatureWorkflowLoggingError | null>;
}

export function createRealtimeFeatureWorkflowState(): RealtimeFeatureWorkflowState {
  return {
    handlersBound: signal(false),
    pendingLoggingAction: signal<RealtimeLoggingPendingAction>(null),
    loggingError: signal<RealtimeFeatureWorkflowLoggingError | null>(null),
  };
}

export interface RealtimeFeatureWorkflowDeps {
  queryClient: QueryClient;
  realtime: RealtimeState;
  t: (key: string, vars?: Record<string, unknown>) => string;
  showError: (message: string) => void;
  isDemoMode: boolean;
  idleCaptureReadinessSignature: ReadonlySignal<string>;
  selection: {
    sendSelection(): void;
  };
  recording: {
    onRecordingStatusChanged(): Promise<void>;
  };
  confirmRemoveClient: (message: string) => Promise<boolean>;
  state?: RealtimeFeatureWorkflowState;
  api?: Partial<RealtimeFeatureWorkflowApi>;
}

export interface RealtimeFeatureWorkflow {
  readonly signals: RealtimeFeatureWorkflowSignals;
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
  return previous.enabled !== next.enabled
    || previous.run_id !== next.run_id
    || previous.analysis_in_progress !== next.analysis_in_progress
    || previous.last_completed_run_id !== next.last_completed_run_id
    || previous.last_completed_run_error !== next.last_completed_run_error;
}

export function createRealtimeFeatureWorkflow(
  deps: RealtimeFeatureWorkflowDeps,
): RealtimeFeatureWorkflow {
  const {
    realtime,
    t,
    showError,
    isDemoMode,
    selection,
    recording,
    confirmRemoveClient,
  } = deps;

  const api: RealtimeFeatureWorkflowApi = {
    getLoggingStatus: deps.api?.getLoggingStatus ?? getLoggingStatusApi,
    startLoggingRun: deps.api?.startLoggingRun ?? startLoggingRunApi,
    stopLoggingRun: deps.api?.stopLoggingRun ?? stopLoggingRunApi,
    getClientLocations: deps.api?.getClientLocations ?? getClientLocationsApi,
    setClientLocation: deps.api?.setClientLocation ?? setClientLocationApi,
    identifyClient: deps.api?.identifyClient ?? identifyClientApi,
    removeClient: deps.api?.removeClient ?? removeClientApi,
  };
  const state = deps.state ?? createRealtimeFeatureWorkflowState();

  let idleCaptureReadinessRefreshInFlight = false;
  let lastIdleCaptureReadinessSignature: string | null = null;
  let queuedIdleCaptureReadinessSignature: string | null = null;
  const idleCaptureReadinessTrigger = computed(() =>
    [
      deps.idleCaptureReadinessSignature.value,
      state.handlersBound.value ? "1" : "0",
      state.pendingLoggingAction.value ?? "",
      realtime.loggingStatus.value.enabled ? "1" : "0",
      realtime.loggingStatus.value.analysis_in_progress ? "1" : "0",
      realtime.loggingStatus.value.last_completed_run_id ? "1" : "0",
    ].join("::")
  );

  function syncIdleCaptureReadinessSignature(): void {
    lastIdleCaptureReadinessSignature = deps.idleCaptureReadinessSignature.peek();
    queuedIdleCaptureReadinessSignature = null;
  }

  function applyLocationCodes(codes: string[]): void {
    realtime.locationCodes.value = codes.length ? codes : defaultLocationCodes.slice();
  }

  async function refreshIdleCaptureReadiness(signature: string): Promise<void> {
    const handlersBound = state.handlersBound.peek();
    const pendingLoggingAction = state.pendingLoggingAction.peek();
    if (
      !handlersBound
      || isDemoMode
      || pendingLoggingAction !== null
    ) {
      return;
    }
    const loggingStatus = realtime.loggingStatus.peek();
    if (
      loggingStatus.enabled
      || loggingStatus.analysis_in_progress
      || Boolean(loggingStatus.last_completed_run_id)
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
      queuedSignature !== null
      && queuedSignature !== lastIdleCaptureReadinessSignature
    ) {
      await refreshIdleCaptureReadiness(queuedSignature);
    }
  }

  const disposeIdleCaptureReadinessSync = effectOnChange(idleCaptureReadinessTrigger, () => {
    void refreshIdleCaptureReadiness(deps.idleCaptureReadinessSignature.peek());
  });

  function handleLoggingStatusData(nextStatus: LoggingStatusPayload): void {
    const previousStatus = realtime.loggingStatus.peek();
    realtime.loggingStatus.value = nextStatus;
    state.loggingError.value = null;
    if (!didHistoryAffectingStatusChange(previousStatus, nextStatus)) {
      return;
    }
    void recording.onRecordingStatusChanged().catch((err) => {
      const message = err instanceof Error ? err.message : t("status.unavailable");
      showError(message || t("status.unavailable"));
    });
  }

  const loggingStatusPollingEnabled = computed(() => state.handlersBound.value && !isDemoMode);

  const loggingStatusQuery = createObservedServerStateQuery<LoggingStatusPayload>({
    enabled: loggingStatusPollingEnabled,
    observerOptions: createHiddenTabPollingObserverOptions<LoggingStatusPayload>(
      (query) => {
        const nextStatus = query.state.data;
        return nextStatus?.enabled || nextStatus?.analysis_in_progress
          ? LOGGING_STATUS_ACTIVE_POLL_MS
          : LOGGING_STATUS_IDLE_POLL_MS;
      },
    ),
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
    queryClient: deps.queryClient,
    queryFn: async () => {
      syncIdleCaptureReadinessSignature();
      if (isDemoMode && state.pendingLoggingAction.peek() === null) {
        state.loggingError.value = null;
        return realtime.loggingStatus.peek();
      }
      return api.getLoggingStatus();
    },
    queryKey: serverStateQueryKeys.realtime.loggingStatus(),
  });

  function bindHandlers(): void {
    if (state.handlersBound.peek()) {
      return;
    }
    state.handlersBound.value = true;
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
      realtime.loggingStatus.value = await api.startLoggingRun();
      await recording.onRecordingStatusChanged();
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
      realtime.loggingStatus.value = await api.stopLoggingRun();
      await recording.onRecordingStatusChanged();
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
    const payload = await deps.queryClient.fetchQuery({
      queryFn: () => api.getClientLocations(),
      queryKey: serverStateQueryKeys.realtime.clientLocations(),
      staleTime: 0,
    });
    const codes = Array.isArray(payload.locations)
      ? payload.locations.map((row) => row.code).filter((code): code is string => typeof code === "string")
      : [];
    applyLocationCodes(codes);
  }

  async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
    if (!clientId) return;
    const clients = realtime.clients.peek();
    const existing = clients.find((client) => client.id === clientId);
    const existingLocationCode = String(existing?.location_code || "").trim();
    if (existing && existingLocationCode === locationCode) return;
    try {
      await api.setClientLocation(clientId, locationCode);
    } catch (err) {
      showError(err instanceof Error ? err.message : t("actions.set_location_failed"));
      return;
    }
    const nextClients = realtime.clients.peek();
    const client = nextClients.find((row) => row.id === clientId);
    if (client) {
      realtime.clients.value = nextClients.map((row) =>
        row.id === clientId ? { ...row, location_code: locationCode } : row
      );
    }
  }

  async function identifyClient(clientId: string): Promise<void> {
    if (!clientId) return;
    await api.identifyClient(clientId);
  }

  async function removeClient(clientId: string): Promise<void> {
    if (!clientId) return;
    const confirmed = await confirmRemoveClient(
      t("actions.remove_client_confirm", { id: clientId }),
    );
    if (!confirmed) return;
    try {
      await api.removeClient(clientId);
    } catch (err) {
      showError(err instanceof Error ? err.message : t("actions.remove_client_failed"));
      return;
    }
    const previousSelectedClientId = realtime.selectedClientId.peek();
    realtime.clients.value = realtime.clients.peek().filter((client) => client.id !== clientId);
    if (realtime.selectedClientId.peek() === clientId) {
      realtime.selectedClientId.value = null;
    }
    syncSelectedRealtimeClient(realtime);
    if (previousSelectedClientId !== realtime.selectedClientId.peek()) {
      selection.sendSelection();
    }
  }

  return {
    dispose(): void {
      loggingStatusQuery.dispose();
      disposeIdleCaptureReadinessSync();
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

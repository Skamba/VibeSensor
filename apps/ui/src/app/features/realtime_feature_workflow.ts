import {
  getClientLocations as getClientLocationsApi,
  getLoggingStatus as getLoggingStatusApi,
  identifyClient as identifyClientApi,
  removeClient as removeClientApi,
  setClientLocation as setClientLocationApi,
  startLoggingRun as startLoggingRunApi,
  stopLoggingRun as stopLoggingRunApi,
} from "../../api";
import { defaultLocationCodes } from "../../constants";
import type {
  ClientLocationsResponse,
  LoggingStatusPayload,
} from "../../transport/http_models";
import {
  trackAppStateSlice,
  syncSelectedRealtimeClient,
  type RealtimeState,
} from "../ui_app_state";
import {
  effect,
  signal,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";
import {
  createPollingController,
  type PollingController,
  type PollingControllerOptions,
} from "./polling_controller";
import type { RealtimeLoggingPendingAction } from "../views/realtime_logging_view_models";

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
  createPollingController?: (options: PollingControllerOptions) => PollingController;
}

export interface RealtimeFeatureWorkflow {
  readonly signals: RealtimeFeatureWorkflowSignals;
  bindHandlers(): void;
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
const LOGGING_STATUS_ERROR_POLL_MS = 5_000;

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
  const createPolling = deps.createPollingController ?? createPollingController;
  const state = deps.state ?? createRealtimeFeatureWorkflowState();

  let idleCaptureReadinessRefreshInFlight = false;
  let lastIdleCaptureReadinessSignature: string | null = null;
  let queuedIdleCaptureReadinessSignature: string | null = null;

  function syncIdleCaptureReadinessSignature(): void {
    lastIdleCaptureReadinessSignature = deps.idleCaptureReadinessSignature.value;
    queuedIdleCaptureReadinessSignature = null;
  }

  function applyLocationCodes(codes: string[]): void {
    realtime.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
  }

  async function refreshIdleCaptureReadiness(signature: string): Promise<void> {
    if (
      !state.handlersBound.value
      || isDemoMode
      || state.pendingLoggingAction.value !== null
    ) {
      return;
    }
    if (
      realtime.loggingStatus.enabled
      || realtime.loggingStatus.analysis_in_progress
      || Boolean(realtime.loggingStatus.last_completed_run_id)
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

  effect(() => {
    trackAppStateSlice(realtime);
    const signature = deps.idleCaptureReadinessSignature.value;
    if (
      !state.handlersBound.value
      || isDemoMode
      || state.pendingLoggingAction.value !== null
    ) {
      return;
    }
    if (
      realtime.loggingStatus.enabled
      || realtime.loggingStatus.analysis_in_progress
      || Boolean(realtime.loggingStatus.last_completed_run_id)
    ) {
      return;
    }
    void refreshIdleCaptureReadiness(signature);
  });

  const loggingStatusPolling = createPolling({
    poll: async () => {
      await refreshLoggingStatus();
      return realtime.loggingStatus.enabled || realtime.loggingStatus.analysis_in_progress
        ? LOGGING_STATUS_ACTIVE_POLL_MS
        : LOGGING_STATUS_IDLE_POLL_MS;
    },
    onErrorDelayMs: LOGGING_STATUS_ERROR_POLL_MS,
  });

  function bindHandlers(): void {
    if (state.handlersBound.value) {
      return;
    }
    state.handlersBound.value = true;
    if (!isDemoMode) {
      loggingStatusPolling.start();
    }
  }

  async function refreshLoggingStatus(): Promise<void> {
    syncIdleCaptureReadinessSignature();
    if (isDemoMode && state.pendingLoggingAction.value === null) {
      state.loggingError.value = null;
      return;
    }
    const previousStatus = realtime.loggingStatus;
    let nextStatus: LoggingStatusPayload;
    try {
      nextStatus = await api.getLoggingStatus();
    } catch {
      state.pendingLoggingAction.value = null;
      state.loggingError.value = {
        kind: "unavailable",
        message: t("status.unavailable"),
      };
      return;
    }
    realtime.loggingStatus = nextStatus;
    state.loggingError.value = null;
    if (!didHistoryAffectingStatusChange(previousStatus, nextStatus)) {
      return;
    }
    try {
      await recording.onRecordingStatusChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : t("status.unavailable");
      showError(message || t("status.unavailable"));
    }
  }

  async function startLogging(): Promise<void> {
    if (state.pendingLoggingAction.value) return;
    syncIdleCaptureReadinessSignature();
    state.pendingLoggingAction.value = "starting";
    state.loggingError.value = null;
    try {
      realtime.loggingStatus = await api.startLoggingRun();
      await recording.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      state.pendingLoggingAction.value = null;
      state.loggingError.value = {
        kind: "error",
        message: message || t("status.unavailable"),
      };
      return;
    }
    state.pendingLoggingAction.value = null;
    state.loggingError.value = null;
  }

  async function stopLogging(): Promise<void> {
    if (state.pendingLoggingAction.value) return;
    syncIdleCaptureReadinessSignature();
    state.pendingLoggingAction.value = "stopping";
    state.loggingError.value = null;
    try {
      realtime.loggingStatus = await api.stopLoggingRun();
      await recording.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      state.pendingLoggingAction.value = null;
      state.loggingError.value = {
        kind: "error",
        message: message || t("status.unavailable"),
      };
      return;
    }
    state.pendingLoggingAction.value = null;
    state.loggingError.value = null;
  }

  async function refreshLocationOptions(): Promise<void> {
    try {
      const payload = await api.getClientLocations();
      const codes = Array.isArray(payload.locations)
        ? payload.locations.map((row) => row.code).filter((code): code is string => typeof code === "string")
        : [];
      applyLocationCodes(codes);
    } catch {
      applyLocationCodes([]);
    }
  }

  async function setClientLocation(clientId: string, locationCode: string): Promise<void> {
    if (!clientId) return;
    const existing = realtime.clients.find((client) => client.id === clientId);
    const existingLocationCode = String(existing?.location_code || "").trim();
    if (existing && existingLocationCode === locationCode) return;
    try {
      await api.setClientLocation(clientId, locationCode);
    } catch (err) {
      showError(err instanceof Error ? err.message : t("actions.set_location_failed"));
      return;
    }
    const client = realtime.clients.find((row) => row.id === clientId);
    if (client) {
      client.location_code = locationCode;
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
    const previousSelectedClientId = realtime.selectedClientId;
    realtime.clients = realtime.clients.filter((client) => client.id !== clientId);
    if (realtime.selectedClientId === clientId) {
      realtime.selectedClientId = null;
    }
    syncSelectedRealtimeClient(realtime);
    if (previousSelectedClientId !== realtime.selectedClientId) {
      selection.sendSelection();
    }
  }

  return {
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

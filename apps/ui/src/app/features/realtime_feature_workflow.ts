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
  LocationOption,
  LoggingStatusPayload,
} from "../../transport/http_models";
import type { AdaptedClient } from "../../transport/live_models";
import {
  syncSelectedRealtimeClient,
  type RealtimeState,
} from "../ui_app_state";
import {
  createPollingController,
  type PollingController,
  type PollingControllerOptions,
} from "./polling_controller";
import type {
  RealtimeFeaturePendingLoggingAction,
  RealtimeFeatureRenderState,
} from "../views/realtime_feature_presenter";

export interface RealtimeFeatureWorkflowApi {
  getLoggingStatus(): Promise<LoggingStatusPayload>;
  startLoggingRun(): Promise<LoggingStatusPayload>;
  stopLoggingRun(): Promise<LoggingStatusPayload>;
  getClientLocations(): Promise<ClientLocationsResponse>;
  setClientLocation(clientId: string, locationCode: string): Promise<void>;
  identifyClient(clientId: string): Promise<void>;
  removeClient(clientId: string): Promise<void>;
}

export interface RealtimeFeatureWorkflowViewPorts {
  buildLocationOptions(codes: readonly string[]): LocationOption[];
  maybeRenderSensorsSettingsList(force?: boolean): void;
  renderStatus(clientRow?: AdaptedClient): void;
  renderLoggingStatus(state: RealtimeFeatureRenderState): void;
  renderLoggingUnavailable(): void;
  renderLoggingError(message: string): void;
  getIdleCaptureReadinessSignature(): string;
}

export interface RealtimeFeatureWorkflowDeps {
  realtime: RealtimeState;
  t: (key: string, vars?: Record<string, unknown>) => string;
  showError: (message: string) => void;
  isDemoMode: boolean;
  view: RealtimeFeatureWorkflowViewPorts;
  selection: {
    sendSelection(): void;
  };
  recording: {
    onRecordingStatusChanged(): Promise<void>;
  };
  confirmRemoveClient: (message: string) => boolean;
  api?: Partial<RealtimeFeatureWorkflowApi>;
  createPollingController?: (options: PollingControllerOptions) => PollingController;
}

export interface RealtimeFeatureWorkflow {
  bindHandlers(): void;
  renderLoggingStatus(): void;
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
    view,
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

  let handlersBound = false;
  let pendingLoggingAction: RealtimeFeaturePendingLoggingAction = null;
  let idleCaptureReadinessRefreshInFlight = false;
  let lastIdleCaptureReadinessSignature: string | null = null;

  function renderState(): RealtimeFeatureRenderState {
    return {
      handlersBound,
      pendingLoggingAction,
    };
  }

  function applyLocationCodes(codes: string[]): void {
    realtime.locationCodes = codes.length ? codes : defaultLocationCodes.slice();
    realtime.locationOptions = view.buildLocationOptions(realtime.locationCodes);
  }

  function requestIdleCaptureReadinessRefresh(): void {
    if (!handlersBound || isDemoMode || pendingLoggingAction !== null) {
      return;
    }
    if (
      realtime.loggingStatus.enabled
      || realtime.loggingStatus.analysis_in_progress
      || Boolean(realtime.loggingStatus.last_completed_run_id)
    ) {
      return;
    }
    const signature = view.getIdleCaptureReadinessSignature();
    if (idleCaptureReadinessRefreshInFlight || lastIdleCaptureReadinessSignature === signature) {
      return;
    }
    lastIdleCaptureReadinessSignature = signature;
    idleCaptureReadinessRefreshInFlight = true;
    void refreshLoggingStatus().finally(() => {
      idleCaptureReadinessRefreshInFlight = false;
    });
  }

  function renderLoggingStatus(): void {
    view.renderLoggingStatus(renderState());
    requestIdleCaptureReadinessRefresh();
  }

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
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    if (!isDemoMode) {
      loggingStatusPolling.start();
    }
    view.renderLoggingStatus(renderState());
  }

  async function refreshLoggingStatus(): Promise<void> {
    if (isDemoMode && pendingLoggingAction === null) {
      renderLoggingStatus();
      return;
    }
    const previousStatus = realtime.loggingStatus;
    let nextStatus: LoggingStatusPayload;
    try {
      nextStatus = await api.getLoggingStatus();
    } catch {
      pendingLoggingAction = null;
      view.renderLoggingUnavailable();
      return;
    }
    realtime.loggingStatus = nextStatus;
    renderLoggingStatus();
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
    if (pendingLoggingAction) return;
    pendingLoggingAction = "starting";
    view.renderLoggingStatus(renderState());
    try {
      realtime.loggingStatus = await api.startLoggingRun();
      await recording.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      pendingLoggingAction = null;
      view.renderLoggingError(message || t("status.unavailable"));
      return;
    }
    pendingLoggingAction = null;
    renderLoggingStatus();
  }

  async function stopLogging(): Promise<void> {
    if (pendingLoggingAction) return;
    pendingLoggingAction = "stopping";
    view.renderLoggingStatus(renderState());
    try {
      realtime.loggingStatus = await api.stopLoggingRun();
      await recording.onRecordingStatusChanged();
      loggingStatusPolling.restart();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      pendingLoggingAction = null;
      view.renderLoggingError(message || t("status.unavailable"));
      return;
    }
    pendingLoggingAction = null;
    renderLoggingStatus();
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
    view.maybeRenderSensorsSettingsList(true);
    view.renderStatus();
    renderLoggingStatus();
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
      view.maybeRenderSensorsSettingsList();
      view.renderStatus();
      await refreshLoggingStatus();
    }
  }

  async function identifyClient(clientId: string): Promise<void> {
    if (!clientId) return;
    await api.identifyClient(clientId);
  }

  async function removeClient(clientId: string): Promise<void> {
    if (!clientId) return;
    const confirmed = confirmRemoveClient(t("actions.remove_client_confirm", { id: clientId }));
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
    view.maybeRenderSensorsSettingsList();
    renderLoggingStatus();
    view.renderStatus();
    if (previousSelectedClientId !== realtime.selectedClientId) {
      selection.sendSelection();
    }
  }

  return {
    bindHandlers,
    renderLoggingStatus,
    refreshLoggingStatus,
    startLogging,
    stopLogging,
    refreshLocationOptions,
    setClientLocation,
    identifyClient,
    removeClient,
  };
}

import {
  cancelUpdate as cancelUpdateApi,
  getHealthStatus as getHealthStatusApi,
  getUpdateInternetStatus as getUpdateInternetStatusApi,
  getUpdateStatus as getUpdateStatusApi,
  startUpdate as startUpdateApi,
} from "../../api/settings";
import {
  UPDATE_POLL_INTERVAL_IDLE_MS,
  UPDATE_POLL_INTERVAL_RUNNING_MS,
} from "../../config";
import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../transport/http_models";
import type {
  UpdateFeatureRenderState,
  UpdateFeatureStartIntent,
} from "../views/update_feature_presenter";
import type { ReadonlySignal } from "../ui_signals";
import {
  createPollingController,
  type PollingController,
  type PollingControllerOptions,
} from "./polling_controller";

export interface UpdateFeatureWorkflowApi {
  cancelUpdate(): Promise<unknown>;
  getHealthStatus(): Promise<HealthStatusPayload>;
  getUpdateInternetStatus(): Promise<unknown>;
  getUpdateStatus(): Promise<UpdateStatusPayload>;
  startUpdate(payload: UpdateStartRequestPayload): Promise<unknown>;
}

export interface UpdateFeatureWorkflowViewPorts {
  render(state: UpdateFeatureRenderState): void;
  focusSsidInput(): void;
  clearPassword(): void;
}

export interface UpdateFeatureWorkflowDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  showError: (message: string) => void;
  view: UpdateFeatureWorkflowViewPorts;
  api?: Partial<UpdateFeatureWorkflowApi>;
  createPollingController?: (options: PollingControllerOptions) => PollingController;
  pollingEnabled?: ReadonlySignal<boolean>;
}

export interface UpdateFeatureWorkflow {
  cancelUpdate(): Promise<void>;
  getRenderState(): UpdateFeatureRenderState;
  refreshStatus(): Promise<void>;
  renderCurrentState(): void;
  startPolling(): void;
  startUpdate(intent: UpdateFeatureStartIntent): Promise<void>;
  stopPolling(): void;
}

function fallbackInternetStatus(
  t: (key: string, vars?: Record<string, unknown>) => string,
): UsbInternetStatusPayload {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: t("settings.internet.load_failed"),
  };
}

function normalizeInternetStatus(
  payload: unknown,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UsbInternetStatusPayload {
  if (!payload || typeof payload !== "object") {
    return fallbackInternetStatus(t);
  }
  const record = payload as Record<string, unknown>;
  return {
    detected: record.detected === true,
    usable: record.usable === true,
    interface_name: typeof record.interface_name === "string" ? record.interface_name : null,
    connection_name: typeof record.connection_name === "string" ? record.connection_name : null,
    driver: typeof record.driver === "string" ? record.driver : null,
    ipv4_addresses: Array.isArray(record.ipv4_addresses)
      ? record.ipv4_addresses.filter((value): value is string => typeof value === "string")
      : [],
    gateway: typeof record.gateway === "string" ? record.gateway : null,
    has_default_route: record.has_default_route === true,
    diagnostic: typeof record.diagnostic === "string"
      ? record.diagnostic
      : t("settings.internet.load_failed"),
  };
}

function safeUpdateTransport(
  transport: string | null | undefined,
): UpdateStartRequestPayload["transport"] {
  return transport === "usb_internet" ? "usb_internet" : "wifi";
}

export function createUpdateFeatureWorkflow(
  deps: UpdateFeatureWorkflowDeps,
): UpdateFeatureWorkflow {
  const api: UpdateFeatureWorkflowApi = {
    cancelUpdate: deps.api?.cancelUpdate ?? cancelUpdateApi,
    getHealthStatus: deps.api?.getHealthStatus ?? getHealthStatusApi,
    getUpdateInternetStatus: deps.api?.getUpdateInternetStatus ?? getUpdateInternetStatusApi,
    getUpdateStatus: deps.api?.getUpdateStatus ?? getUpdateStatusApi,
    startUpdate: deps.api?.startUpdate ?? startUpdateApi,
  };
  const createPolling = deps.createPollingController ?? createPollingController;

  let latestInternetStatus: UsbInternetStatusPayload = fallbackInternetStatus(deps.t);
  let latestHealthStatus: HealthStatusPayload | null = null;
  let latestUpdateStatus: UpdateStatusPayload | null = null;
  let latestUpdateState: UpdateStatusPayload["state"] = "idle";
  let latestUpdateTransport: UpdateStartRequestPayload["transport"] = "wifi";

  function getRenderState(): UpdateFeatureRenderState {
    return {
      internetStatus: latestInternetStatus,
      healthStatus: latestHealthStatus,
      updateStatus: latestUpdateStatus,
      updateState: latestUpdateState,
      updateTransport: latestUpdateTransport,
    };
  }

  function renderCurrentState(): void {
    deps.view.render(getRenderState());
  }

  async function fetchStatusSnapshot(): Promise<{
    health: HealthStatusPayload;
    internet: UsbInternetStatusPayload;
    status: UpdateStatusPayload;
  }> {
    const [status, health, internet] = await Promise.all([
      api.getUpdateStatus(),
      api.getHealthStatus(),
      api.getUpdateInternetStatus()
        .then((payload) => normalizeInternetStatus(payload, deps.t))
        .catch(() => fallbackInternetStatus(deps.t)),
    ]);
    return {
      health,
      internet,
      status,
    };
  }

  function applyStatusSnapshot(snapshot: {
    health: HealthStatusPayload;
    internet: UsbInternetStatusPayload;
    status: UpdateStatusPayload;
  }): void {
    latestUpdateStatus = snapshot.status;
    latestHealthStatus = snapshot.health;
    latestInternetStatus = snapshot.internet;
    latestUpdateState = snapshot.status.state;
    latestUpdateTransport = safeUpdateTransport(snapshot.status.transport);
    renderCurrentState();
  }

  const polling = createPolling({
    enabled: deps.pollingEnabled,
    poll: async () => {
      const snapshot = await fetchStatusSnapshot();
      applyStatusSnapshot(snapshot);
      return snapshot.status.state === "running"
        ? UPDATE_POLL_INTERVAL_RUNNING_MS
        : UPDATE_POLL_INTERVAL_IDLE_MS;
    },
    onErrorDelayMs: UPDATE_POLL_INTERVAL_RUNNING_MS,
  });

  async function refreshStatus(): Promise<void> {
    applyStatusSnapshot(await fetchStatusSnapshot());
  }

  async function startUpdate(intent: UpdateFeatureStartIntent): Promise<void> {
    if (!intent.canStart) {
      if (intent.transport === "wifi" && !intent.ssid) {
        deps.view.focusSsidInput();
      }
      return;
    }
    if (intent.transport === "wifi") {
      if (!intent.ssid) {
        deps.view.focusSsidInput();
        return;
      }
    } else if (!intent.usbAvailable) {
      deps.showError(deps.t("settings.update.usb_unavailable"));
      return;
    }

    const payload: UpdateStartRequestPayload = intent.transport === "wifi"
      ? {
          transport: intent.transport,
          ssid: intent.ssid,
          password: intent.password,
        }
      : {
          transport: intent.transport,
          password: "",
        };

    try {
      await api.startUpdate(payload);
      deps.view.clearPassword();
      polling.restart();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409")) {
        deps.showError(deps.t("settings.update.already_running"));
      } else {
        deps.showError(`${deps.t("settings.update.start_failed")}\n${msg}`);
      }
    }
  }

  async function cancelUpdate(): Promise<void> {
    try {
      await api.cancelUpdate();
      polling.restart();
    } catch {
      /* ignore */
    }
  }

  return {
    cancelUpdate,
    getRenderState,
    refreshStatus,
    renderCurrentState,
    startPolling() {
      polling.start();
    },
    startUpdate,
    stopPolling() {
      polling.stop();
    },
  };
}

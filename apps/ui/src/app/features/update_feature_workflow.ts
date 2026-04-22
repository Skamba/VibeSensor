import type { QueryClient } from "@tanstack/query-core";

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
} from "../../api/types";
import type {
  UpdateFeatureRenderState,
  UpdateFeatureStartIntent,
} from "../views/update_feature_presenter";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";

export interface UpdateFeatureWorkflowApi {
  cancelUpdate(): Promise<unknown>;
  getHealthStatus(): Promise<HealthStatusPayload>;
  getUpdateInternetStatus(): Promise<UsbInternetStatusPayload>;
  getUpdateStatus(): Promise<UpdateStatusPayload>;
  startUpdate(payload: UpdateStartRequestPayload): Promise<unknown>;
}

export interface UpdateFeatureWorkflowViewPorts {
  focusSsidInput(): void;
  clearPassword(): void;
}

export interface UpdateFeatureWorkflowDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  showError: (message: string) => void;
  queryClient: QueryClient;
  view: UpdateFeatureWorkflowViewPorts;
  api?: Partial<UpdateFeatureWorkflowApi>;
  pollingEnabled?: ReadonlySignal<boolean>;
}

export interface UpdateFeatureWorkflow {
  cancelUpdate(): Promise<void>;
  dispose(): void;
  getRenderState(): UpdateFeatureRenderState;
  readonly renderState: ReadonlySignal<UpdateFeatureRenderState>;
  refreshStatus(): Promise<void>;
  startUpdate(intent: UpdateFeatureStartIntent): Promise<void>;
}

interface UpdateStatusSnapshot {
  health: HealthStatusPayload;
  internet: UsbInternetStatusPayload;
  status: UpdateStatusPayload;
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

  const latestInternetStatus = signal<UsbInternetStatusPayload>(fallbackInternetStatus(deps.t));
  const latestHealthStatus = signal<HealthStatusPayload | null>(null);
  const latestUpdateStatus = signal<UpdateStatusPayload | null>(null);
  const latestUpdateState = signal<UpdateStatusPayload["state"]>("idle");
  const latestUpdateTransport = signal<UpdateStartRequestPayload["transport"]>("wifi");
  const renderState = computed<UpdateFeatureRenderState>(() => ({
    internetStatus: latestInternetStatus.value,
    healthStatus: latestHealthStatus.value,
    updateStatus: latestUpdateStatus.value,
    updateState: latestUpdateState.value,
    updateTransport: latestUpdateTransport.value,
  }));

  function getRenderState(): UpdateFeatureRenderState {
    return renderState.value;
  }

  async function fetchStatusSnapshot(): Promise<UpdateStatusSnapshot> {
    const [status, health, internet] = await Promise.all([
      api.getUpdateStatus(),
      api.getHealthStatus(),
      api.getUpdateInternetStatus(),
    ]);
    return {
      health,
      internet,
      status,
    };
  }

  function applyStatusSnapshot(snapshot: UpdateStatusSnapshot): void {
    batch(() => {
      latestUpdateStatus.value = snapshot.status;
      latestHealthStatus.value = snapshot.health;
      latestInternetStatus.value = snapshot.internet;
      latestUpdateState.value = snapshot.status.state;
      latestUpdateTransport.value = safeUpdateTransport(snapshot.status.transport);
    });
  }

  const statusSnapshotQuery = createObservedServerStateQuery<UpdateStatusSnapshot>({
    enabled: deps.pollingEnabled,
    onError: (error) => {
      deps.showError(error instanceof Error ? error.message : deps.t("status.unavailable"));
    },
    observerOptions: createHiddenTabPollingObserverOptions<UpdateStatusSnapshot>(
      (query) => query.state.data?.status.state === "running"
        ? UPDATE_POLL_INTERVAL_RUNNING_MS
        : UPDATE_POLL_INTERVAL_IDLE_MS,
    ),
    onData: applyStatusSnapshot,
    queryClient: deps.queryClient,
    queryFn: fetchStatusSnapshot,
    queryKey: serverStateQueryKeys.update.statusSnapshot(),
  });

  async function refreshStatus(): Promise<void> {
    await statusSnapshotQuery.fetch();
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
      await statusSnapshotQuery.fetch();
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
      await statusSnapshotQuery.fetch();
    } catch {
      /* ignore */
    }
  }

  return {
    cancelUpdate,
    dispose(): void {
      statusSnapshotQuery.dispose();
    },
    getRenderState,
    renderState,
    refreshStatus,
    startUpdate,
  };
}

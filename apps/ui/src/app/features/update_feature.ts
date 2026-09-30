import type { QueryClient } from "@tanstack/query-core";

import {
  cancelUpdate as cancelUpdateApi,
  getHealthStatus,
  getUpdateInternetStatus,
  getUpdateStatus,
  startUpdate as startUpdateApi,
} from "../../api/settings";
import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../api/types";
import {
  UPDATE_POLL_INTERVAL_IDLE_MS,
  UPDATE_POLL_INTERVAL_RUNNING_MS,
} from "../../config";
import type { FeatureServices } from "../feature_deps_base";
import { batch, computed, signal, type ReadonlySignal } from "../ui_signals";
import type { InternetPanelView } from "../views/internet_panel";
import {
  createUpdateFeaturePresenter,
  type UpdateFeatureRenderState,
  type UpdateFeatureStartIntent,
} from "../views/update_feature_presenter";
import type { UpdatePanelView } from "../views/update_panel";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  cancelUpdate(): Promise<void>;
  dispose(): void;
  refreshStatus(): Promise<void>;
  readonly renderState: ReadonlySignal<UpdateFeatureRenderState>;
  /** Starts an update for an explicit intent (the panel passes its form state). */
  startUpdate(intent: UpdateFeatureStartIntent): Promise<void>;
}

interface UpdateStatusSnapshot {
  health: HealthStatusPayload;
  internet: UsbInternetStatusPayload;
  status: UpdateStatusPayload;
}

function fallbackInternetStatus(
  t: FeatureServices["t"],
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

async function fetchStatusSnapshot(): Promise<UpdateStatusSnapshot> {
  const [status, health, internet] = await Promise.all([
    getUpdateStatus(),
    getHealthStatus(),
    getUpdateInternetStatus(),
  ]);
  return { health, internet, status };
}

/**
 * Updater controller: query-backed update/health/internet polling while the
 * internet or update settings tab is visible, plus start/cancel commands,
 * behind the typed update and internet panel bridges.
 */
export function createUpdateFeature(ctx: {
  panels: { update: UpdatePanelView; internet: InternetPanelView };
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  queryClient: QueryClient;
  services: Pick<FeatureServices, "t" | "showError">;
}): UpdateFeature {
  const { panels } = ctx;
  const { t, showError } = ctx.services;
  const handlersBound = signal(false);
  const pollingEnabled = computed(
    () =>
      handlersBound.value &&
      ctx.activeViewId.value === "settingsView" &&
      (ctx.activeSettingsTabId.value === "internetTab" ||
        ctx.activeSettingsTabId.value === "updateTab"),
  );

  const latestInternetStatus = signal<UsbInternetStatusPayload>(
    fallbackInternetStatus(t),
  );
  const latestHealthStatus = signal<HealthStatusPayload | null>(null);
  const latestUpdateStatus = signal<UpdateStatusPayload | null>(null);
  const latestUpdateState = signal<UpdateStatusPayload["state"]>("idle");
  const latestUpdateTransport =
    signal<UpdateStartRequestPayload["transport"]>("wifi");
  const renderState = computed<UpdateFeatureRenderState>(() => ({
    internetStatus: latestInternetStatus.value,
    healthStatus: latestHealthStatus.value,
    updateStatus: latestUpdateStatus.value,
    updateState: latestUpdateState.value,
    updateTransport: latestUpdateTransport.value,
  }));
  const presenter = createUpdateFeaturePresenter({ renderState, t });
  panels.internet.model.value = presenter.internetPanelModel;
  panels.update.model.value = presenter.updatePanelModel;

  let disposed = false;
  let statusGeneration = 0;
  let startInFlight = false;
  let cancelInFlight = false;

  function nextStatusGeneration(): number {
    statusGeneration += 1;
    return statusGeneration;
  }

  function isCurrentStatus(generation: number): boolean {
    return !disposed && generation === statusGeneration;
  }

  function applyStatusSnapshot(snapshot: UpdateStatusSnapshot): void {
    if (disposed) {
      return;
    }
    batch(() => {
      latestUpdateStatus.value = snapshot.status;
      latestHealthStatus.value = snapshot.health;
      latestInternetStatus.value = snapshot.internet;
      latestUpdateState.value = snapshot.status.state;
      latestUpdateTransport.value = safeUpdateTransport(
        snapshot.status.transport,
      );
    });
  }

  const statusSnapshotQuery =
    createObservedServerStateQuery<UpdateStatusSnapshot>({
      enabled: pollingEnabled,
      onError: (error) => {
        if (!disposed) {
          showError(
            error instanceof Error ? error.message : t("status.unavailable"),
          );
        }
      },
      observerOptions:
        createHiddenTabPollingObserverOptions<UpdateStatusSnapshot>((query) =>
          query.state.data?.status.state === "running"
            ? UPDATE_POLL_INTERVAL_RUNNING_MS
            : UPDATE_POLL_INTERVAL_IDLE_MS,
        ),
      onData: applyStatusSnapshot,
      queryClient: ctx.queryClient,
      queryFn: fetchStatusSnapshot,
      queryKey: serverStateQueryKeys.update.statusSnapshot(),
    });

  async function refreshStatusForGeneration(generation: number): Promise<void> {
    const snapshot = await fetchStatusSnapshot();
    if (!isCurrentStatus(generation)) {
      return;
    }
    statusSnapshotQuery.setData(() => snapshot);
    applyStatusSnapshot(snapshot);
  }

  async function refreshStatus(): Promise<void> {
    if (disposed) {
      return;
    }
    const generation = nextStatusGeneration();
    try {
      await refreshStatusForGeneration(generation);
    } catch (error) {
      if (isCurrentStatus(generation)) {
        showError(
          error instanceof Error ? error.message : t("status.unavailable"),
        );
      }
      throw error;
    }
  }

  async function startUpdate(intent: UpdateFeatureStartIntent): Promise<void> {
    if (disposed || startInFlight) {
      return;
    }
    if (!intent.canStart) {
      if (intent.transport === "wifi" && !intent.ssid) {
        panels.internet.focusSsidInput();
      }
      return;
    }
    if (intent.transport === "wifi") {
      if (!intent.ssid) {
        panels.internet.focusSsidInput();
        return;
      }
    } else if (!intent.usbAvailable) {
      showError(t("settings.update.usb_unavailable"));
      return;
    }

    const payload: UpdateStartRequestPayload =
      intent.transport === "wifi"
        ? {
            transport: intent.transport,
            ssid: intent.ssid,
            password: intent.password,
          }
        : {
            transport: intent.transport,
            password: "",
          };

    startInFlight = true;
    const generation = nextStatusGeneration();
    try {
      await startUpdateApi(payload);
      if (!isCurrentStatus(generation)) {
        return;
      }
      presenter.clearPassword();
      await refreshStatusForGeneration(generation);
    } catch (err) {
      if (!isCurrentStatus(generation)) {
        return;
      }
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409")) {
        showError(t("settings.update.already_running"));
      } else {
        showError(`${t("settings.update.start_failed")}\n${msg}`);
      }
    } finally {
      startInFlight = false;
    }
  }

  async function cancelUpdate(): Promise<void> {
    if (disposed || cancelInFlight) {
      return;
    }
    cancelInFlight = true;
    const generation = nextStatusGeneration();
    try {
      await cancelUpdateApi();
    } catch {
      /* ignore */
    } finally {
      try {
        if (isCurrentStatus(generation)) {
          await refreshStatusForGeneration(generation);
        }
      } finally {
        cancelInFlight = false;
      }
    }
  }

  return {
    bindUpdateHandlers(): void {
      if (handlersBound.value) {
        return;
      }
      handlersBound.value = true;
      panels.update.actions.value = {
        onStart: () => {
          void startUpdate(presenter.readStartIntent());
        },
        onCancel: () => {
          void cancelUpdate();
        },
      };
      panels.internet.actions.value = {
        onPasswordInput: presenter.setPasswordInput,
        onTogglePassword: presenter.togglePassword,
        onTransportChange: presenter.setSelectedTransport,
        onSsidInput: presenter.setSsidInput,
      };
    },
    cancelUpdate,
    dispose(): void {
      disposed = true;
      statusGeneration += 1;
      startInFlight = false;
      cancelInFlight = false;
      statusSnapshotQuery.dispose();
    },
    refreshStatus,
    renderState,
    startUpdate,
  };
}

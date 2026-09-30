import type { QueryClient } from "@tanstack/query-core";

import {
  cancelEspFlash,
  getEspFlashHistory,
  getEspFlashLogs,
  getEspFlashPorts,
  getEspFlashStatus,
  startEspFlash,
} from "../../api/settings";
import { ESP_FLASH_POLL_ACTIVE_MS, ESP_FLASH_POLL_IDLE_MS } from "../../config";
import type {
  EspFlashHistoryPayload,
  EspFlashLogsPayload,
  EspFlashPortsPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../api/types";
import type { FeatureServices } from "../feature_deps_base";
import {
  batch,
  computed,
  effectOnChange,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import {
  buildEspFlashPanelRenderModel,
  type EspFlashFeatureRenderState,
} from "../views/esp_flash_feature_presenter";
import type { EspFlashPanelView } from "../views/esp_flash_panel";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";

export interface EspFlashFeature {
  bindHandlers(): void;
  cancelFlash(): Promise<void>;
  dispose(): void;
  readonly renderState: ReadonlySignal<EspFlashFeatureRenderState>;
  refreshPorts(): Promise<void>;
  refreshStatus(): Promise<void>;
  setSelectedPortValue(value: string): void;
  startFlash(): Promise<void>;
}

interface EspFlashStatusSnapshot {
  attempts: readonly NonNullable<EspFlashHistoryPayload["attempts"]>[number][];
  logText: string;
  nextLogIndex: number;
  status: EspFlashStatusPayload;
}

function createIdleStatus(): EspFlashStatusPayload {
  return {
    auto_detect: true,
    error: null,
    exit_code: null,
    finished_at: null,
    job_id: null,
    last_success_at: null,
    log_count: 0,
    phase: "idle",
    selected_port: null,
    started_at: null,
    state: "idle",
  };
}

function safeEspFlashState(state: string | null | undefined): string {
  return state || "idle";
}

/**
 * ESP flash controller: query-backed port refreshes, flash status/log/history
 * polling while the ESP flash tab is visible, and start/cancel orchestration
 * behind the typed ESP flash panel bridge.
 */
export function createEspFlashFeature(ctx: {
  panel: EspFlashPanelView;
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  queryClient: QueryClient;
  services: Pick<FeatureServices, "t" | "showError">;
}): EspFlashFeature {
  const { panel, queryClient } = ctx;
  const { t, showError } = ctx.services;
  const handlersBound = signal(false);
  const pollingEnabled = computed(
    () =>
      handlersBound.value &&
      ctx.activeViewId.value === "settingsView" &&
      ctx.activeSettingsTabId.value === "espFlashTab",
  );
  const latestStatus = signal<EspFlashStatusPayload>(createIdleStatus());
  const lastJourneyPhase = signal<string | null>(null);
  const availablePorts = signal<readonly EspSerialPortPayload[]>([]);
  const selectedPortValue = signal("__auto__");
  const logText = signal("");
  const latestAttempts = signal<
    readonly NonNullable<EspFlashHistoryPayload["attempts"]>[number][]
  >([]);
  const renderState = computed<EspFlashFeatureRenderState>(() => ({
    attempts: [...latestAttempts.value],
    availablePorts: [...availablePorts.value],
    lastJourneyPhase: lastJourneyPhase.value,
    logText: logText.value,
    selectedPortValue: selectedPortValue.value,
    status: latestStatus.value,
  }));
  let disposed = false;
  let statusGeneration = 0;
  let portsGeneration = 0;
  let flashInFlight = false;
  let cancelInFlight = false;

  function nextStatusGeneration(): number {
    statusGeneration += 1;
    return statusGeneration;
  }

  function isCurrentStatus(generation: number): boolean {
    return !disposed && generation === statusGeneration;
  }

  function nextPortsGeneration(): number {
    portsGeneration += 1;
    return portsGeneration;
  }

  function isCurrentPorts(generation: number): boolean {
    return !disposed && generation === portsGeneration;
  }

  function updateJourneyPhase(status: EspFlashStatusPayload): void {
    if (disposed) {
      return;
    }
    const phase = status.phase || null;
    const safeState = safeEspFlashState(status.state);
    const isJourneyPhase = [
      "validating",
      "preparing",
      "erasing",
      "flashing",
      "done",
    ].includes(phase || "");
    if (isJourneyPhase) {
      lastJourneyPhase.value = phase;
      return;
    }
    if (safeState === "idle" || safeState === "success") {
      lastJourneyPhase.value = null;
    }
  }

  function applyStatus(status: EspFlashStatusPayload): void {
    if (disposed) {
      return;
    }
    updateJourneyPhase(status);
    latestStatus.value = status;
  }

  async function fetchStatusSnapshot(): Promise<EspFlashStatusSnapshot> {
    const previous = queryClient.getQueryData<EspFlashStatusSnapshot>(
      serverStateQueryKeys.espFlash.statusSnapshot(),
    );
    const status = await getEspFlashStatus();
    let logText = status.log_count === 0 ? "" : (previous?.logText ?? "");
    let nextLogIndex =
      status.log_count === 0 ? 0 : (previous?.nextLogIndex ?? 0);
    if (status.log_count > 0) {
      if (nextLogIndex === 0) {
        logText = "";
      }
      const logs = await getEspFlashLogs(nextLogIndex);
      if (logs.lines.length > 0) {
        logText += `${logs.lines.join("\n")}\n`;
      }
      nextLogIndex = logs.next_index;
    }
    const history = await getEspFlashHistory();
    return {
      attempts: history.attempts || [],
      logText,
      nextLogIndex,
      status,
    };
  }

  function applyStatusSnapshot(snapshot: EspFlashStatusSnapshot): void {
    if (disposed) {
      return;
    }
    batch(() => {
      applyStatus(snapshot.status);
      latestAttempts.value = snapshot.attempts;
      logText.value = snapshot.logText;
    });
  }

  const statusSnapshotQuery =
    createObservedServerStateQuery<EspFlashStatusSnapshot>({
      enabled: pollingEnabled,
      observerOptions:
        createHiddenTabPollingObserverOptions<EspFlashStatusSnapshot>(
          (query) =>
            safeEspFlashState(query.state.data?.status.state) === "running"
              ? ESP_FLASH_POLL_ACTIVE_MS
              : ESP_FLASH_POLL_IDLE_MS,
        ),
      onData: (snapshot) => {
        if (!disposed) {
          applyStatusSnapshot(snapshot);
        }
      },
      queryClient: queryClient,
      queryFn: fetchStatusSnapshot,
      queryKey: serverStateQueryKeys.espFlash.statusSnapshot(),
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
    await refreshStatusForGeneration(generation);
  }

  async function refreshPorts(): Promise<void> {
    if (disposed) {
      return;
    }
    const generation = nextPortsGeneration();
    const payload = await queryClient.fetchQuery({
      queryFn: () => getEspFlashPorts(),
      queryKey: serverStateQueryKeys.espFlash.ports(),
      staleTime: 0,
    });
    if (!isCurrentPorts(generation)) {
      return;
    }
    const ports = payload.ports || [];
    batch(() => {
      availablePorts.value = ports;
      if (!ports.some((port) => port.port === selectedPortValue.peek())) {
        selectedPortValue.value = "__auto__";
      }
    });
  }

  async function startFlash(): Promise<void> {
    if (disposed || flashInFlight) {
      return;
    }
    const latestState = safeEspFlashState(latestStatus.peek().state);
    const ports = availablePorts.peek();
    if (latestState === "running" || ports.length === 0) {
      return;
    }
    const selectedPort = selectedPortValue.peek();
    const autoDetect = selectedPort === "__auto__";
    const port = autoDetect ? null : selectedPort;
    flashInFlight = true;
    const generation = nextStatusGeneration();
    try {
      await startEspFlash(port, autoDetect);
      if (!isCurrentStatus(generation)) {
        return;
      }
      logText.value = "";
      statusSnapshotQuery.setData(() => undefined);
      await refreshStatusForGeneration(generation);
    } catch (err) {
      if (isCurrentStatus(generation)) {
        showError(
          `${t("settings.esp_flash.start_failed")}\n${err instanceof Error ? err.message : String(err)}`,
        );
      }
    } finally {
      flashInFlight = false;
    }
  }

  async function cancelFlash(): Promise<void> {
    if (disposed || cancelInFlight) {
      return;
    }
    cancelInFlight = true;
    const generation = nextStatusGeneration();
    try {
      await cancelEspFlash();
    } catch {
      /* cancel may race the job finishing; resync through polling */
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

  function setSelectedPortValue(value: string): void {
    if (disposed) {
      return;
    }
    selectedPortValue.value = value || "__auto__";
  }

  panel.model.value = computed(() =>
    buildEspFlashPanelRenderModel(renderState.value, { t }),
  );

  // Entering the ESP flash tab re-lists serial ports.
  const disposePollingContextSync = effectOnChange(
    pollingEnabled,
    (enabled) => {
      if (enabled) {
        void refreshPorts();
      }
    },
  );

  return {
    bindHandlers(): void {
      if (handlersBound.value) {
        return;
      }
      handlersBound.value = true;
      panel.actions.value = {
        onStart: () => {
          void startFlash();
        },
        onCancel: () => {
          void cancelFlash();
        },
        onRefreshPorts: () => {
          void refreshPorts();
        },
        onSelectPort: setSelectedPortValue,
      };
    },
    cancelFlash,
    dispose(): void {
      disposePollingContextSync();
      disposed = true;
      statusGeneration += 1;
      portsGeneration += 1;
      flashInFlight = false;
      cancelInFlight = false;
      statusSnapshotQuery.dispose();
    },
    renderState,
    refreshPorts,
    refreshStatus,
    setSelectedPortValue,
    startFlash,
  };
}

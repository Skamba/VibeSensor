import {
  cancelEspFlash as cancelEspFlashApi,
  getEspFlashHistory as getEspFlashHistoryApi,
  getEspFlashLogs as getEspFlashLogsApi,
  getEspFlashPorts as getEspFlashPortsApi,
  getEspFlashStatus as getEspFlashStatusApi,
  startEspFlash as startEspFlashApi,
} from "../../api/settings";
import {
  ESP_FLASH_POLL_ACTIVE_MS,
  ESP_FLASH_POLL_IDLE_MS,
} from "../../config";
import type {
  EspFlashHistoryPayload,
  EspFlashLogsPayload,
  EspFlashPortsPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
  } from "../../transport/http_models";
import type { EspFlashFeatureRenderState } from "../views/esp_flash_feature_presenter";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import {
  createPollingController,
  type PollingController,
  type PollingControllerOptions,
} from "./polling_controller";

export interface EspFlashFeatureWorkflowApi {
  cancelEspFlash(): Promise<unknown>;
  getEspFlashHistory(): Promise<EspFlashHistoryPayload>;
  getEspFlashLogs(after: number): Promise<EspFlashLogsPayload>;
  getEspFlashPorts(): Promise<EspFlashPortsPayload>;
  getEspFlashStatus(): Promise<EspFlashStatusPayload>;
  startEspFlash(port: string | null, autoDetect: boolean): Promise<unknown>;
}

export interface EspFlashFeatureWorkflowDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  showError: (message: string) => void;
  api?: Partial<EspFlashFeatureWorkflowApi>;
  createPollingController?: (options: PollingControllerOptions) => PollingController;
  pollingEnabled?: ReadonlySignal<boolean>;
}

export interface EspFlashFeatureWorkflow {
  cancelFlash(): Promise<void>;
  getRenderState(): EspFlashFeatureRenderState;
  readonly renderState: ReadonlySignal<EspFlashFeatureRenderState>;
  refreshPorts(): Promise<void>;
  refreshStatus(): Promise<void>;
  setSelectedPortValue(value: string): void;
  startFlash(): Promise<void>;
  startPolling(): void;
  stopPolling(): void;
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

export function createEspFlashFeatureWorkflow(
  deps: EspFlashFeatureWorkflowDeps,
): EspFlashFeatureWorkflow {
  const api: EspFlashFeatureWorkflowApi = {
    cancelEspFlash: deps.api?.cancelEspFlash ?? cancelEspFlashApi,
    getEspFlashHistory: deps.api?.getEspFlashHistory ?? getEspFlashHistoryApi,
    getEspFlashLogs: deps.api?.getEspFlashLogs ?? getEspFlashLogsApi,
    getEspFlashPorts: deps.api?.getEspFlashPorts ?? getEspFlashPortsApi,
    getEspFlashStatus: deps.api?.getEspFlashStatus ?? getEspFlashStatusApi,
    startEspFlash: deps.api?.startEspFlash ?? startEspFlashApi,
  };
  const createPolling = deps.createPollingController ?? createPollingController;

  let nextLogIndex = 0;
  const latestStatus = signal<EspFlashStatusPayload>(createIdleStatus());
  const lastJourneyPhase = signal<string | null>(null);
  const availablePorts = signal<readonly EspSerialPortPayload[]>([]);
  const selectedPortValue = signal("__auto__");
  const logText = signal("");
  const latestAttempts = signal<readonly NonNullable<EspFlashHistoryPayload["attempts"]>[number][]>([]);
  const renderState = computed<EspFlashFeatureRenderState>(() => ({
    attempts: [...latestAttempts.value],
    availablePorts: [...availablePorts.value],
    lastJourneyPhase: lastJourneyPhase.value,
    logText: logText.value,
    selectedPortValue: selectedPortValue.value,
    status: latestStatus.value,
  }));

  function getRenderState(): EspFlashFeatureRenderState {
    return renderState.value;
  }

  function updateJourneyPhase(status: EspFlashStatusPayload): void {
    const phase = status.phase || null;
    const safeState = safeEspFlashState(status.state);
    const isJourneyPhase = ["validating", "preparing", "erasing", "flashing", "done"].includes(
      phase || "",
    );
    if (isJourneyPhase) {
      lastJourneyPhase.value = phase;
      return;
    }
    if (safeState === "idle" || safeState === "success") {
      lastJourneyPhase.value = null;
    }
  }

  async function refreshHistory(): Promise<void> {
    try {
      const payload = await api.getEspFlashHistory();
      latestAttempts.value = payload.attempts || [];
    } catch {
      /* keep existing history on transient error */
    }
  }

  async function refreshLogs(status: EspFlashStatusPayload): Promise<void> {
    if ((status.log_count || 0) === 0) {
      logText.value = "";
      nextLogIndex = 0;
      return;
    }
    if (nextLogIndex === 0) {
      logText.value = "";
    }
    const logs = await api.getEspFlashLogs(nextLogIndex);
    if (logs.lines.length > 0) {
      logText.value += `${logs.lines.join("\n")}\n`;
    }
    nextLogIndex = logs.next_index;
  }

  function applyStatus(status: EspFlashStatusPayload): void {
    updateJourneyPhase(status);
    latestStatus.value = status;
    if (safeEspFlashState(status.state) !== "running") {
      nextLogIndex = status.log_count || 0;
    }
  }

  async function refreshStatus(): Promise<void> {
    const status = await api.getEspFlashStatus();
    batch(() => {
      applyStatus(status);
    });
    await refreshLogs(status);
    await refreshHistory();
  }

  async function refreshPorts(): Promise<void> {
    try {
      const payload = await api.getEspFlashPorts();
      const ports = payload.ports || [];
      batch(() => {
        availablePorts.value = ports;
        if (!ports.some((port) => port.port === selectedPortValue.value)) {
          selectedPortValue.value = "__auto__";
        }
      });
    } catch {
      /* keep existing options on transient error */
    }
  }

  const polling = createPolling({
    enabled: deps.pollingEnabled,
    poll: async () => {
      await refreshStatus();
      return safeEspFlashState(latestStatus.value.state) === "running"
        ? ESP_FLASH_POLL_ACTIVE_MS
        : ESP_FLASH_POLL_IDLE_MS;
    },
    onErrorDelayMs: ESP_FLASH_POLL_ACTIVE_MS,
  });

  async function startFlash(): Promise<void> {
    if (
      safeEspFlashState(latestStatus.value.state) === "running"
      || availablePorts.value.length === 0
    ) {
      return;
    }
    const autoDetect = selectedPortValue.value === "__auto__";
    const port = autoDetect ? null : selectedPortValue.value;
    try {
      await api.startEspFlash(port, autoDetect);
      logText.value = "";
      nextLogIndex = 0;
      polling.restart();
    } catch (err) {
      deps.showError(
        `${deps.t("settings.esp_flash.start_failed")}\n${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  async function cancelFlash(): Promise<void> {
    try {
      await api.cancelEspFlash();
    } catch {
      /* cancel may race the job finishing; resync through polling */
    }
    polling.restart();
  }

  return {
    cancelFlash,
    getRenderState,
    renderState,
    refreshPorts,
    refreshStatus,
    setSelectedPortValue(value: string) {
      selectedPortValue.value = value || "__auto__";
    },
    startFlash,
    startPolling() {
      void refreshPorts();
      polling.start();
    },
    stopPolling() {
      polling.stop();
    },
  };
}

import { batch, computed, effect, signal } from "@preact/signals";

import {
  cancelEspFlash,
  getEspFlashHistory,
  getEspFlashLogs,
  getEspFlashPorts,
  getEspFlashStatus,
  startEspFlash,
} from "../../api/settings";
import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../../api/types";
import {
  activeView,
  errorMessage,
  settingsTab,
  showError,
} from "../../app_store";
import { ESP_FLASH_POLL_ACTIVE_MS, ESP_FLASH_POLL_IDLE_MS } from "../../config";
import { t } from "../../i18n";
import { poll } from "../../poll";
import { AUTO_PORT, type FlashView, nextJourneyPhase } from "./esp_flash_model";

const IDLE_STATUS: EspFlashStatusPayload = {
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

const status = signal<EspFlashStatusPayload>(IDLE_STATUS);
const ports = signal<readonly EspSerialPortPayload[]>([]);
const attempts = signal<readonly EspFlashHistoryAttemptPayload[]>([]);
const lastJourneyPhase = signal<string | null>(null);
export const selectedPort = signal(AUTO_PORT);
export const logText = signal("");

export const flashView = computed<FlashView>(() => ({
  status: status.value,
  ports: ports.value,
  selectedPort: selectedPort.value,
  attempts: attempts.value,
  lastJourneyPhase: lastJourneyPhase.value,
}));

interface Snapshot {
  status: EspFlashStatusPayload;
  attempts: readonly EspFlashHistoryAttemptPayload[];
  log: { text: string; next: number };
}

/** Log lines already fetched; each snapshot appends only the new ones. */
let log = { text: "", next: 0 };

async function loadSnapshot(): Promise<Snapshot> {
  const nextStatus = await getEspFlashStatus();
  let nextLog = nextStatus.log_count === 0 ? { text: "", next: 0 } : log;
  if (nextStatus.log_count > 0) {
    const page = await getEspFlashLogs(nextLog.next);
    nextLog = {
      text:
        page.lines.length > 0
          ? `${nextLog.text}${page.lines.join("\n")}\n`
          : nextLog.text,
      next: page.next_index,
    };
  }
  const history = await getEspFlashHistory();
  return { status: nextStatus, attempts: history.attempts ?? [], log: nextLog };
}

const tabVisible = computed(
  () =>
    activeView.value === "settingsView" && settingsTab.value === "espFlashTab",
);

const snapshots = poll({
  active: tabVisible,
  intervalMs: (last) =>
    last?.status.state === "running"
      ? ESP_FLASH_POLL_ACTIVE_MS
      : ESP_FLASH_POLL_IDLE_MS,
  load: loadSnapshot,
  onData: (snapshot) => {
    log = snapshot.log;
    batch(() => {
      lastJourneyPhase.value = nextJourneyPhase(
        lastJourneyPhase.value,
        snapshot.status,
      );
      status.value = snapshot.status;
      attempts.value = snapshot.attempts;
      logText.value = snapshot.log.text;
    });
  },
});

let portsRequest = 0;

export async function refreshPorts(): Promise<void> {
  const request = ++portsRequest;
  const payload = await getEspFlashPorts();
  if (request !== portsRequest) {
    return;
  }
  const nextPorts = payload.ports ?? [];
  batch(() => {
    ports.value = nextPorts;
    if (!nextPorts.some((port) => port.port === selectedPort.value)) {
      selectedPort.value = AUTO_PORT;
    }
  });
}

// Opening the tab re-lists the serial ports.
effect(() => {
  if (tabVisible.value) {
    void refreshPorts();
  }
});

let startInFlight = false;
let cancelInFlight = false;

export async function startFlash(): Promise<void> {
  if (
    startInFlight ||
    status.value.state === "running" ||
    ports.value.length === 0
  ) {
    return;
  }
  startInFlight = true;
  const port = selectedPort.value === AUTO_PORT ? null : selectedPort.value;
  try {
    await startEspFlash(port, port === null);
    log = { text: "", next: 0 };
    logText.value = "";
    await snapshots.refresh();
  } catch (error) {
    showError(
      `${t("settings.esp_flash.start_failed")}\n${errorMessage(error, String(error))}`,
    );
  } finally {
    startInFlight = false;
  }
}

export async function cancelFlash(): Promise<void> {
  if (cancelInFlight) {
    return;
  }
  cancelInFlight = true;
  try {
    await cancelEspFlash();
  } catch {
    // Cancel can race the job finishing; the refresh below resyncs.
  }
  try {
    await snapshots.refresh();
  } finally {
    cancelInFlight = false;
  }
}

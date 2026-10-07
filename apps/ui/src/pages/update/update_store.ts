import { batch, computed, effect, signal } from "@preact/signals";

import {
  cancelUpdate as cancelUpdateApi,
  getHealthStatus,
  getUpdateInternetStatus,
  getUpdateStatus,
  startUpdate as startUpdateApi,
} from "../../api/settings";
import type {
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../api/types";
import {
  activeView,
  errorMessage,
  settingsTab,
  showError,
} from "../../app_store";
import {
  UPDATE_POLL_INTERVAL_IDLE_MS,
  UPDATE_POLL_INTERVAL_RUNNING_MS,
} from "../../config";
import { t } from "../../i18n";
import { poll } from "../../poll";
import {
  activeTransport,
  canStart,
  offlineInternetStatus,
  type Transport,
  type UpdateView,
} from "./update_model";

const status = signal<UpdateStatusPayload | null>(null);
const health = signal<HealthStatusPayload | null>(null);
const internet = signal<UsbInternetStatusPayload | null>(null);
export const transportChoice = signal<Transport>("wifi");
export const ssid = signal("");
export const password = signal("");
export const passwordVisible = signal(false);
/** Bumped to move focus to the SSID input. */
export const ssidFocusRequest = signal(0);

export const updateView = computed<UpdateView>(() => ({
  status: status.value,
  health: health.value,
  internet: internet.value ?? offlineInternetStatus(t),
  transportChoice: transportChoice.value,
  ssid: ssid.value,
}));

const tabVisible = computed(
  () =>
    activeView.value === "settingsView" && settingsTab.value === "updateTab",
);

let ssidHydrated = false;

const snapshots = poll({
  active: tabVisible,
  intervalMs: (last) =>
    last?.status.state === "running"
      ? UPDATE_POLL_INTERVAL_RUNNING_MS
      : UPDATE_POLL_INTERVAL_IDLE_MS,
  load: async () => {
    const [nextStatus, nextHealth, nextInternet] = await Promise.all([
      getUpdateStatus(),
      getHealthStatus(),
      getUpdateInternetStatus(),
    ]);
    return { status: nextStatus, health: nextHealth, internet: nextInternet };
  },
  onData: (snapshot) => {
    batch(() => {
      status.value = snapshot.status;
      health.value = snapshot.health;
      internet.value = snapshot.internet;
      // Prefill the SSID of the last Wi-Fi update once.
      if (!ssidHydrated) {
        ssidHydrated = true;
        if (
          snapshot.status.transport === "wifi" &&
          snapshot.status.ssid &&
          !ssid.value.trim()
        ) {
          ssid.value = snapshot.status.ssid;
        }
      }
    });
  },
  onError: (error) => showError(errorMessage(error, t("status.unavailable"))),
});

// While a job runs, the form follows the transport it actually uses.
effect(() => {
  const current = status.value;
  if (current?.state === "running") {
    transportChoice.value =
      current.transport === "usb_internet" ? "usb_internet" : "wifi";
  }
});

let startInFlight = false;
let cancelInFlight = false;

export async function startUpdate(): Promise<void> {
  if (startInFlight) {
    return;
  }
  const view = updateView.value;
  const transport = activeTransport(view);
  const wifiSsid = view.ssid.trim();
  if (transport === "wifi" && !wifiSsid) {
    settingsTab.value = "updateTab";
    ssidFocusRequest.value += 1;
    return;
  }
  if (!canStart(view, t)) {
    return;
  }
  startInFlight = true;
  try {
    await startUpdateApi(
      transport === "wifi"
        ? { transport, ssid: wifiSsid, password: password.value }
        : { transport, password: "" },
    );
    password.value = "";
    await snapshots.refresh();
  } catch (error) {
    const message = errorMessage(error, String(error));
    showError(
      message.includes("409")
        ? t("settings.update.already_running")
        : `${t("settings.update.start_failed")}\n${message}`,
    );
  } finally {
    startInFlight = false;
  }
}

export async function cancelUpdate(): Promise<void> {
  if (cancelInFlight) {
    return;
  }
  cancelInFlight = true;
  try {
    await cancelUpdateApi();
  } catch {
    // The job may already be finishing; the refresh below resyncs.
  }
  try {
    await snapshots.refresh();
  } finally {
    cancelInFlight = false;
  }
}

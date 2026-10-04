import { batch, computed, signal } from "@preact/signals";

import {
  pairSettingsObdDevice,
  scanSettingsObdDevices,
  updateSettingsSpeedSource,
} from "../../api/settings";
import type { ObdDevicePayload, SpeedSourceKind } from "../../api/types";
import {
  activeView,
  errorMessage,
  onViewEnter,
  settingsTab,
  showError,
} from "../../app_store";
import type { Feedback } from "../../components/feedback";
import { t } from "../../i18n";
import { poll } from "../../poll";
import {
  applySpeedSource,
  loadSpeedSource,
  refreshSpeedStatus,
  speedSettings,
  speedSourceSnapshot,
  speedStatus,
} from "../../settings_store";
import {
  activeSourceLabel,
  checkSave,
  compareDevices,
} from "./speed_source_model";

const OBD_RESCAN_MS = 2_000;

/** Unsaved edits; `null` means "show the saved value". */
const modeDraft = signal<SpeedSourceKind | null>(null);
const manualSpeedDraft = signal<string | null>(null);
const staleTimeoutDraft = signal<string | null>(null);

/** The saved choice, even while a manual fallback stands in for a lost live source. */
export const savedMode = computed(() => speedSettings.source.value);
export const selectedMode = computed(() => modeDraft.value ?? savedMode.value);
export const draftPending = computed(
  () => modeDraft.value !== null && modeDraft.value !== savedMode.value,
);
export const manualSpeedInput = computed(
  () =>
    manualSpeedDraft.value ??
    (speedSettings.manualSpeedKph.value != null
      ? String(speedSettings.manualSpeedKph.value)
      : ""),
);
export const staleTimeoutInput = computed(
  () =>
    staleTimeoutDraft.value ??
    (speedSettings.staleTimeoutS.value != null
      ? String(speedSettings.staleTimeoutS.value)
      : ""),
);

export const manualSpeedFeedback = signal<Feedback | null>(null);
export const staleTimeoutFeedback = signal<Feedback | null>(null);
export const saveFeedback = signal<Feedback | null>(null);
export const obdSelectionError = signal(false);
export const diagnosticsOpen = signal(false);
/** Bumped to move focus: which field and a counter so repeats re-focus. */
export const focusRequest = signal<{
  field: "manual" | "stale" | "scan";
  seq: number;
} | null>(null);

export const scannedDevices = signal<readonly ObdDevicePayload[]>([]);
export const scanInFlight = signal(false);
export const pairingMac = signal<string | null>(null);
export const scanStatus = signal<string | null>(null);
const rescanRequested = signal(false);

function requestFocus(field: "manual" | "stale" | "scan"): void {
  focusRequest.value = { field, seq: (focusRequest.peek()?.seq ?? 0) + 1 };
}

function clearFeedback(): void {
  batch(() => {
    manualSpeedFeedback.value = null;
    staleTimeoutFeedback.value = null;
    saveFeedback.value = null;
    obdSelectionError.value = false;
  });
}

function showSaveProblem(body: string, detail: string): void {
  batch(() => {
    saveFeedback.value = {
      title: t("settings.speed.save_failed_title"),
      body,
      detail,
      tone: "error",
    };
    diagnosticsOpen.value = true;
  });
}

let loaded = false;
// Opening Settings loads the saved source once, then refreshes the status.
onViewEnter("settingsView", async () => {
  if (loaded) {
    return;
  }
  try {
    await loadSpeedSource();
    loaded = true;
    batch(() => {
      modeDraft.value = null;
      manualSpeedDraft.value = null;
      staleTimeoutDraft.value = null;
    });
  } finally {
    await refreshSpeedStatus();
  }
});

export function chooseMode(mode: SpeedSourceKind): void {
  batch(() => {
    modeDraft.value = mode;
    clearFeedback();
  });
}

export function editManualSpeed(value: string): void {
  batch(() => {
    manualSpeedDraft.value = value;
    manualSpeedFeedback.value = null;
    saveFeedback.value = null;
  });
}

export function editStaleTimeout(value: string): void {
  batch(() => {
    staleTimeoutDraft.value = value;
    staleTimeoutFeedback.value = null;
    saveFeedback.value = null;
  });
}

let saveInFlight = false;

export async function saveSpeedSource(): Promise<void> {
  if (saveInFlight) {
    return;
  }
  clearFeedback();
  const activeSource = activeSourceLabel(
    speedSourceSnapshot.value,
    speedStatus.value,
    t,
  );
  const check = checkSave({
    source: modeDraft.value ?? speedSettings.source.value,
    manualSpeed: manualSpeedInput.value,
    staleTimeout: staleTimeoutInput.value,
    obdDeviceMac: speedSettings.obdDeviceMac.value,
  });
  if (!check.ok) {
    const detail = t("settings.speed.validation_active_detail", {
      source: activeSource,
    });
    batch(() => {
      if (check.problem === "manual_speed") {
        manualSpeedFeedback.value = {
          body: t("settings.speed.manual_invalid"),
          compact: true,
          tone: "error",
        };
        showSaveProblem(t("settings.speed.manual_invalid"), detail);
      } else if (check.problem === "stale_timeout") {
        staleTimeoutFeedback.value = {
          body: t("settings.speed.stale_timeout_invalid"),
          compact: true,
          tone: "error",
        };
        showSaveProblem(t("settings.speed.stale_timeout_invalid"), detail);
      } else {
        obdSelectionError.value = true;
        showSaveProblem(t("settings.speed.obd_missing_device_error"), detail);
      }
    });
    requestFocus(
      check.problem === "manual_speed"
        ? "manual"
        : check.problem === "stale_timeout"
          ? "stale"
          : "scan",
    );
    return;
  }
  saveInFlight = true;
  try {
    const saved = await updateSettingsSpeedSource(check.request);
    batch(() => {
      applySpeedSource(saved);
      modeDraft.value = null;
      manualSpeedDraft.value = null;
      staleTimeoutDraft.value = null;
      clearFeedback();
    });
    await refreshSpeedStatus();
  } catch (error) {
    showSaveProblem(
      errorMessage(error, t("settings.save_failed")),
      t("settings.speed.save_failed_detail", { source: activeSource }),
    );
  } finally {
    saveInFlight = false;
  }
}

function mergeDevices(devices: readonly ObdDevicePayload[]): void {
  const byMac = new Map(
    scannedDevices.value.map((device) => [device.mac_address, device]),
  );
  for (const device of devices) {
    byMac.set(device.mac_address, device);
  }
  scannedDevices.value = [...byMac.values()].sort(compareDevices);
}

export async function scanDevices(): Promise<void> {
  if (scanInFlight.value || pairingMac.value !== null) {
    return;
  }
  batch(() => {
    scanInFlight.value = true;
    obdSelectionError.value = false;
    saveFeedback.value = null;
    scanStatus.value = t("settings.speed.obd_scanning");
  });
  try {
    const { devices } = await scanSettingsObdDevices();
    batch(() => {
      rescanRequested.value = true;
      scannedDevices.value = [...devices].sort(compareDevices);
      scanStatus.value =
        devices.length > 0
          ? t("settings.speed.obd_scan_found", { count: devices.length })
          : t("settings.speed.obd_scan_empty");
    });
  } catch (error) {
    scanStatus.value = t("settings.speed.obd_scan_failed");
    showError(errorMessage(error, t("settings.speed.obd_scan_failed")));
  } finally {
    scanInFlight.value = false;
  }
}

export async function pairDevice(macAddress: string): Promise<void> {
  if (pairingMac.value !== null) {
    return;
  }
  batch(() => {
    obdSelectionError.value = false;
    saveFeedback.value = null;
    pairingMac.value = macAddress;
    scanStatus.value = t("settings.speed.obd_pairing");
  });
  try {
    const paired = await pairSettingsObdDevice(macAddress);
    batch(() => {
      speedSettings.obdDeviceMac.value = paired.configured_device_mac ?? null;
      speedSettings.obdDeviceName.value = paired.configured_device_name ?? null;
      mergeDevices([
        {
          connected: paired.connected,
          mac_address: paired.configured_device_mac ?? macAddress,
          name: paired.configured_device_name ?? null,
          paired: paired.paired,
          rfcomm_channel: paired.rfcomm_channel,
          trusted: paired.trusted,
        },
      ]);
      scanStatus.value = t("settings.speed.obd_pair_success");
    });
    await refreshSpeedStatus();
  } catch (error) {
    scanStatus.value = t("settings.speed.obd_pair_failed");
    showError(errorMessage(error, t("settings.speed.obd_pair_failed")));
  } finally {
    pairingMac.value = null;
  }
}

// After a manual scan, keep merging rescans so newly advertising adapters
// show up while OBD-II is selected on the visible tab.
poll({
  active: computed(
    () =>
      rescanRequested.value &&
      activeView.value === "settingsView" &&
      settingsTab.value === "speedSourceTab" &&
      selectedMode.value === "obd2" &&
      !scanInFlight.value &&
      pairingMac.value === null,
  ),
  intervalMs: OBD_RESCAN_MS,
  load: scanSettingsObdDevices,
  onData: ({ devices }) => mergeDevices(devices),
});

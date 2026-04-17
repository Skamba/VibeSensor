import type {
  ObdDevicePayload,
  SpeedSourceKind,
  SpeedSourcePayload,
  SpeedSourceRequest,
} from "../../api/types";
import {
  createSpeedSourceDerivedState,
  resolveEffectiveSpeedSource,
  type DisplayedSpeedSourceMode,
} from "../speed_source_state";
import {
  batchAppStateUpdates,
  trackAppStateSlice,
  type SettingsState,
} from "../ui_app_state";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import type { SettingsSpeedSourceRenderState } from "../views/settings_speed_source_presenter";
import type { SettingsFeedbackMessage } from "../views/settings_feedback";
import {
  createPollingController,
  type PollingController,
  type PollingControllerOptions,
} from "./polling_controller";
import {
  createSettingsSpeedSourceTransport,
  type SettingsSpeedSourceTransport,
} from "./settings_speed_source_transport";

const OBD_BACKGROUND_RESCAN_DELAY_MS = 2_000;

export interface SettingsSpeedSourceWorkflowViewPorts {
  focusManualSpeedInput(): void;
  focusScanObdDevices(): void;
  focusStaleTimeoutInput(): void;
  isObdConfigVisible(): boolean;
}

export interface SettingsSpeedSourceWorkflowDeps {
  createPollingController?: (options: PollingControllerOptions) => PollingController;
  renderSpeedReadout: () => void;
  settings: SettingsState;
  showError: (message: string) => void;
  t: (key: string, vars?: Record<string, unknown>) => string;
  transport?: Partial<SettingsSpeedSourceTransport>;
  view: SettingsSpeedSourceWorkflowViewPorts;
}

export interface SettingsSpeedSourceWorkflow {
  getRenderState(): SettingsSpeedSourceRenderState;
  readonly renderState: ReadonlySignal<SettingsSpeedSourceRenderState>;
  handleManualSpeedInput(value: string): void;
  handleNavigateContext(): void;
  handleSpeedSourceChanged(mode: DisplayedSpeedSourceMode): void;
  handleStaleTimeoutInput(value: string): void;
  loadSpeedSourceFromServer(): Promise<void>;
  pairObdDevice(macAddress: string): Promise<void>;
  saveSpeedSource(): Promise<void>;
  scanObdDevices(mode?: "manual" | "background"): Promise<void>;
  syncFromSettings(): void;
  syncInputsFromSettings(): void;
}

function parseManualSpeedKph(rawValue: number): number | null {
  return Number.isFinite(rawValue) && rawValue > 0 && rawValue <= 500 ? rawValue : null;
}

function activeSourceLabel(
  settings: SettingsState,
  t: SettingsSpeedSourceWorkflowDeps["t"],
): string {
  const effectiveSource = resolveEffectiveSpeedSource(settings);
  if (effectiveSource === "fallback_manual") {
    return t("settings.speed.current_source_fallback_manual");
  }
  if (effectiveSource === "manual") {
    return t("settings.speed.current_source_manual_override");
  }
  if (effectiveSource === "gps" || effectiveSource == null) {
    return t("settings.speed.gps");
  }
  if (effectiveSource === "obd2") {
    return t("dashboard.rotational.source.obd2");
  }
  return effectiveSource;
}

function looksLikeMacAlias(rawValue: string | null | undefined): boolean {
  const value = rawValue?.trim();
  return value != null && /^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(value);
}

function hasHumanReadableDeviceName(device: ObdDevicePayload): boolean {
  const value = device.name?.trim();
  return Boolean(value) && !looksLikeMacAlias(value);
}

function compareScannedDevices(left: ObdDevicePayload, right: ObdDevicePayload): number {
  const leftConnectedRank = Number(!left.connected);
  const rightConnectedRank = Number(!right.connected);
  if (leftConnectedRank !== rightConnectedRank) {
    return leftConnectedRank - rightConnectedRank;
  }
  const leftPairedRank = Number(!left.paired);
  const rightPairedRank = Number(!right.paired);
  if (leftPairedRank !== rightPairedRank) {
    return leftPairedRank - rightPairedRank;
  }
  const leftNamedRank = Number(!hasHumanReadableDeviceName(left));
  const rightNamedRank = Number(!hasHumanReadableDeviceName(right));
  if (leftNamedRank !== rightNamedRank) {
    return leftNamedRank - rightNamedRank;
  }
  const leftName = left.name?.trim() || left.mac_address;
  const rightName = right.name?.trim() || right.mac_address;
  const labelCompare = leftName.localeCompare(rightName);
  if (labelCompare !== 0) {
    return labelCompare;
  }
  return left.mac_address.localeCompare(right.mac_address);
}

function cloneFeedback(
  message: SettingsFeedbackMessage | null,
): SettingsFeedbackMessage | null {
  return message ? { ...message } : null;
}

export function createSettingsSpeedSourceWorkflow(
  deps: SettingsSpeedSourceWorkflowDeps,
): SettingsSpeedSourceWorkflow {
  const transport = createSettingsSpeedSourceTransport(deps.transport);
  const createPolling = deps.createPollingController ?? createPollingController;
  const speedSourceState = createSpeedSourceDerivedState(deps.settings);
  const speedSourceDraftDirty = signal(false);
  const selectedMode = signal<DisplayedSpeedSourceMode>(speedSourceState.displayedMode.value);
  const manualSpeedInputValue = signal(
    deps.settings.manualSpeedKph != null ? String(deps.settings.manualSpeedKph) : "",
  );
  const staleTimeoutInputValue = signal("");
  let speedSourceContextVisible = false;
  let backgroundRescanRequested = false;
  const scannedDevices = signal<readonly ObdDevicePayload[]>([]);
  const scanInFlight = signal(false);
  const pairInFlightMac = signal<string | null>(null);
  const obdScanStatusMessage = signal<string | null>(null);
  const manualSpeedFeedback = signal<SettingsFeedbackMessage | null>(null);
  const staleTimeoutFeedback = signal<SettingsFeedbackMessage | null>(null);
  const saveFeedback = signal<SettingsFeedbackMessage | null>(null);
  const obdSelectionError = signal(false);
  const diagnosticsOpen = signal(false);
  const renderState = computed<SettingsSpeedSourceRenderState>(() => {
    const trackedSettings = trackAppStateSlice(deps.settings);
    return {
      diagnosticsOpen: diagnosticsOpen.value,
      draftDirty: speedSourceDraftDirty.value,
      manualSpeedFeedback: cloneFeedback(manualSpeedFeedback.value),
      manualSpeedInputValue: manualSpeedInputValue.value,
      obdScanStatusMessage: obdScanStatusMessage.value,
      obdSelectionError: obdSelectionError.value,
      pairInFlightMac: pairInFlightMac.value,
      saveFeedback: cloneFeedback(saveFeedback.value),
      scannedDevices: [...scannedDevices.value],
      scanInFlight: scanInFlight.value,
      selectedMode: selectedMode.value,
      settings: {
        gpsFallbackActive: trackedSettings.gpsFallbackActive,
        gpsEffectiveSpeedKph: trackedSettings.gpsEffectiveSpeedKph,
        manualSpeedKph: trackedSettings.manualSpeedKph,
        obdDeviceMac: trackedSettings.obdDeviceMac,
        obdDeviceName: trackedSettings.obdDeviceName,
        resolvedSpeedSource: trackedSettings.resolvedSpeedSource,
        speedSource: trackedSettings.speedSource,
      },
      staleTimeoutFeedback: cloneFeedback(staleTimeoutFeedback.value),
      staleTimeoutInputValue: staleTimeoutInputValue.value,
    };
  });

  function getRenderState(): SettingsSpeedSourceRenderState {
    return renderState.value;
  }

  function shouldRunBackgroundRescan(): boolean {
    return backgroundRescanRequested
      && speedSourceContextVisible
      && selectedMode.value === "obd2"
      && !scanInFlight.value
      && pairInFlightMac.value === null;
  }

  function syncBackgroundRescan(): void {
    if (shouldRunBackgroundRescan()) {
      obdBackgroundRescan.start();
      return;
    }
    obdBackgroundRescan.stop();
  }

  function syncContextVisibility(): void {
    speedSourceContextVisible = deps.view.isObdConfigVisible();
    syncBackgroundRescan();
  }

  let contextSyncScheduled = false;
  function scheduleContextVisibilitySync(): void {
    if (contextSyncScheduled) {
      return;
    }
    contextSyncScheduled = true;
    queueMicrotask(() => {
      contextSyncScheduled = false;
      syncContextVisibility();
    });
  }

  function clearManualSpeedFeedback(): void {
    batch(() => {
      manualSpeedFeedback.value = null;
      saveFeedback.value = null;
    });
  }

  function clearStaleTimeoutFeedback(): void {
    batch(() => {
      staleTimeoutFeedback.value = null;
      saveFeedback.value = null;
    });
  }

  function clearObdSelectionFeedback(): void {
    batch(() => {
      obdSelectionError.value = false;
      saveFeedback.value = null;
    });
  }

  function clearAllFeedback(): void {
    batch(() => {
      manualSpeedFeedback.value = null;
      staleTimeoutFeedback.value = null;
      saveFeedback.value = null;
      obdSelectionError.value = false;
    });
  }

  function showSaveFeedback(message: string, detail: string): void {
    batch(() => {
      saveFeedback.value = {
        body: message,
        detail,
        title: deps.t("settings.speed.save_failed_title"),
        tone: "error",
      };
      diagnosticsOpen.value = true;
    });
  }

  function setScannedDevices(devices: readonly ObdDevicePayload[]): void {
    scannedDevices.value = [...devices].sort(compareScannedDevices);
  }

  function mergeScannedDevices(devices: readonly ObdDevicePayload[]): void {
    const merged = new Map(scannedDevices.value.map((device) => [device.mac_address, device]));
    devices.forEach((device) => {
      merged.set(device.mac_address, device);
    });
    setScannedDevices(Array.from(merged.values()));
  }

  function syncInputsFromSettings(): void {
    batch(() => {
      speedSourceDraftDirty.value = false;
      selectedMode.value = speedSourceState.displayedMode.value;
      manualSpeedInputValue.value = deps.settings.manualSpeedKph != null
        ? String(deps.settings.manualSpeedKph)
        : "";
      manualSpeedFeedback.value = null;
      staleTimeoutFeedback.value = null;
      saveFeedback.value = null;
      obdSelectionError.value = false;
    });
    scheduleContextVisibilitySync();
  }

  function syncFromSettings(): void {
    if (!speedSourceDraftDirty.value) {
      batch(() => {
        selectedMode.value = speedSourceState.displayedMode.value;
        manualSpeedInputValue.value = deps.settings.manualSpeedKph != null
          ? String(deps.settings.manualSpeedKph)
          : "";
      });
    }
    scheduleContextVisibilitySync();
  }

  function applyPayload(payload: SpeedSourcePayload): void {
    batch(() => {
      batchAppStateUpdates(() => {
        deps.settings.speedSource = payload.speed_source;
        deps.settings.manualSpeedKph = payload.manual_speed_kph;
        deps.settings.obdDeviceMac = payload.obd_device_mac ?? null;
        deps.settings.obdDeviceName = payload.obd_device_name ?? null;
        deps.settings.resolvedSpeedSource = null;
      });
      staleTimeoutInputValue.value = String(payload.stale_timeout_s);
      syncInputsFromSettings();
    });
    deps.renderSpeedReadout();
  }

  async function loadSpeedSourceFromServer(): Promise<void> {
    try {
      const payload = await transport.loadSpeedSource();
      applyPayload(payload);
    } catch {
      /* keep the current UI state on transient load errors */
    }
  }

  function handleSpeedSourceChanged(mode: DisplayedSpeedSourceMode): void {
    batch(() => {
      speedSourceDraftDirty.value = true;
      selectedMode.value = mode;
      clearAllFeedback();
    });
    scheduleContextVisibilitySync();
  }

  function handleManualSpeedInput(value: string): void {
    batch(() => {
      manualSpeedInputValue.value = value;
      clearManualSpeedFeedback();
    });
  }

  function handleStaleTimeoutInput(value: string): void {
    batch(() => {
      staleTimeoutInputValue.value = value;
      clearStaleTimeoutFeedback();
    });
  }

  async function saveSpeedSource(): Promise<void> {
    clearAllFeedback();

    const source: SpeedSourceKind = speedSourceDraftDirty.value
      ? selectedMode.value
      : deps.settings.speedSource;
    const manualInputValue = manualSpeedInputValue.value.trim();
    const manualSpeedKph = parseManualSpeedKph(Number(manualInputValue));
    const staleValueRaw = staleTimeoutInputValue.value.trim();
    const staleValue = Number(staleValueRaw);
    const staleTimeoutInvalid = source !== "manual" && (
      staleValueRaw === ""
      || Number.isNaN(staleValue)
      || !Number.isFinite(staleValue)
      || staleValue < 3
      || staleValue > 120
    );
    const manualSpeedInvalid = (source === "manual" && manualSpeedKph == null)
      || (manualInputValue !== "" && manualSpeedKph == null);
    const activeSource = activeSourceLabel(deps.settings, deps.t);

    if (manualSpeedInvalid) {
      batch(() => {
        manualSpeedFeedback.value = {
          body: deps.t("settings.speed.manual_invalid"),
          compact: true,
          tone: "error",
        };
        showSaveFeedback(
          deps.t("settings.speed.manual_invalid"),
          deps.t("settings.speed.validation_active_detail", { source: activeSource }),
        );
      });
      deps.view.focusManualSpeedInput();
      return;
    }

    if (staleTimeoutInvalid) {
      batch(() => {
        staleTimeoutFeedback.value = {
          body: deps.t("settings.speed.stale_timeout_invalid"),
          compact: true,
          tone: "error",
        };
        showSaveFeedback(
          deps.t("settings.speed.stale_timeout_invalid"),
          deps.t("settings.speed.validation_active_detail", { source: activeSource }),
        );
      });
      deps.view.focusStaleTimeoutInput();
      return;
    }

    if (source === "obd2" && !deps.settings.obdDeviceMac) {
      batch(() => {
        obdSelectionError.value = true;
        showSaveFeedback(
          deps.t("settings.speed.obd_missing_device_error"),
          deps.t("settings.speed.validation_active_detail", { source: activeSource }),
        );
      });
      deps.view.focusScanObdDevices();
      return;
    }

    const payload: SpeedSourceRequest = {
      manual_speed_kph: manualSpeedKph,
      speed_source: source,
    };
    if (staleValue >= 3 && staleValue <= 120) {
      payload.stale_timeout_s = staleValue;
    }

    try {
      const saved = await transport.saveSpeedSource(payload);
      applyPayload(saved);
    } catch (error) {
      showSaveFeedback(
        error instanceof Error ? error.message : deps.t("settings.save_failed"),
        deps.t("settings.speed.save_failed_detail", { source: activeSource }),
      );
    }
  }

  async function scanObdDevices(mode: "manual" | "background" = "manual"): Promise<void> {
    if (scanInFlight.value || pairInFlightMac.value !== null) {
      return;
    }
    batch(() => {
      scanInFlight.value = true;
      if (mode === "manual") {
        clearObdSelectionFeedback();
        obdScanStatusMessage.value = deps.t("settings.speed.obd_scanning");
      }
    });
    syncBackgroundRescan();
    try {
      const payload = await transport.scanObdDevices();
      if (mode === "manual") {
        backgroundRescanRequested = true;
        batch(() => {
          setScannedDevices(payload.devices);
          obdScanStatusMessage.value = payload.devices.length > 0
            ? deps.t("settings.speed.obd_scan_found", { count: payload.devices.length })
            : deps.t("settings.speed.obd_scan_empty");
        });
        syncBackgroundRescan();
      } else {
        mergeScannedDevices(payload.devices);
      }
    } catch (error) {
      if (mode === "manual") {
        obdScanStatusMessage.value = deps.t("settings.speed.obd_scan_failed");
        deps.showError(error instanceof Error ? error.message : deps.t("settings.speed.obd_scan_failed"));
      }
    } finally {
      scanInFlight.value = false;
      syncBackgroundRescan();
    }
  }

  async function pairObdDevice(macAddress: string): Promise<void> {
    clearObdSelectionFeedback();
    batch(() => {
      pairInFlightMac.value = macAddress;
      obdScanStatusMessage.value = deps.t("settings.speed.obd_pairing");
    });
    syncBackgroundRescan();
    try {
      const payload = await transport.pairObdDevice(macAddress);
      batch(() => {
        batchAppStateUpdates(() => {
          deps.settings.obdDeviceMac = payload.configured_device_mac ?? null;
          deps.settings.obdDeviceName = payload.configured_device_name ?? null;
        });
        mergeScannedDevices([{
          connected: payload.connected,
          mac_address: payload.configured_device_mac ?? macAddress,
          name: payload.configured_device_name ?? null,
          paired: payload.paired,
          rfcomm_channel: payload.rfcomm_channel,
          trusted: payload.trusted,
        }]);
        obdScanStatusMessage.value = deps.t("settings.speed.obd_pair_success");
      });
    } catch (error) {
      obdScanStatusMessage.value = deps.t("settings.speed.obd_pair_failed");
      deps.showError(error instanceof Error ? error.message : deps.t("settings.speed.obd_pair_failed"));
    } finally {
      pairInFlightMac.value = null;
      syncBackgroundRescan();
    }
  }

  function handleNavigateContext(): void {
    syncContextVisibility();
  }

  const obdBackgroundRescan = createPolling({
    onErrorDelayMs: OBD_BACKGROUND_RESCAN_DELAY_MS,
    poll: async () => {
      if (!shouldRunBackgroundRescan()) {
        return OBD_BACKGROUND_RESCAN_DELAY_MS;
      }
      await scanObdDevices("background");
      return OBD_BACKGROUND_RESCAN_DELAY_MS;
    },
  });

  return {
    getRenderState,
    renderState,
    handleManualSpeedInput,
    handleNavigateContext,
    handleSpeedSourceChanged,
    handleStaleTimeoutInput,
    loadSpeedSourceFromServer,
    pairObdDevice,
    saveSpeedSource,
    scanObdDevices,
    syncFromSettings,
    syncInputsFromSettings,
  };
}

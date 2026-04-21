import type { QueryClient } from "@tanstack/query-core";

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
  type SpeedSourceStateSnapshot,
} from "../speed_source_state";
import type { SettingsState } from "../ui_app_state";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
} from "../ui_signals";
import type { SettingsSpeedSourceRenderState } from "../views/settings_speed_source_presenter";
import type { SettingsFeedbackMessage } from "../views/settings_feedback";
import {
  createSettingsSpeedSourceTransport,
  type SettingsSpeedSourceTransport,
} from "./settings_speed_source_transport";
import { createObservedServerStateQuery } from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";

const OBD_BACKGROUND_RESCAN_DELAY_MS = 2_000;

export interface SettingsSpeedSourceWorkflowViewPorts {
  focusManualSpeedInput(): void;
  focusScanObdDevices(): void;
  focusStaleTimeoutInput(): void;
}

export interface SettingsSpeedSourceWorkflowDeps {
  obdConfigVisible: ReadonlySignal<boolean>;
  queryClient: QueryClient;
  settings: SettingsState;
  showError: (message: string) => void;
  t: (key: string, vars?: Record<string, unknown>) => string;
  transport?: Partial<SettingsSpeedSourceTransport>;
  view: SettingsSpeedSourceWorkflowViewPorts;
}

export interface SettingsSpeedSourceWorkflow {
  dispose(): void;
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
  const effectiveSource = resolveEffectiveSpeedSource({
    speedSource: settings.speed.source.value,
    manualSpeedKph: settings.speed.manualSpeedKph.value,
    resolvedSpeedSource: settings.speed.resolvedSource.value,
  });
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
  const speedSourceState = createSpeedSourceDerivedState(deps.settings.speed);
  const selectedModeDraft = signal<DisplayedSpeedSourceMode | null>(null);
  const manualSpeedInputDraft = signal<string | null>(null);
  const selectedMode = computed<DisplayedSpeedSourceMode>(() =>
    selectedModeDraft.value ?? speedSourceState.displayedMode.value
  );
  const manualSpeedInputValue = computed(() => {
    const draft = manualSpeedInputDraft.value;
    if (draft != null) {
      return draft;
    }
    return deps.settings.speed.manualSpeedKph.value != null
      ? String(deps.settings.speed.manualSpeedKph.value)
      : "";
  });
  const staleTimeoutInputValue = signal("");
  const speedSourceContextVisible = signal(false);
  const backgroundRescanRequested = signal(false);
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
    const settingsSnapshot: SpeedSourceStateSnapshot & {
      gpsFallbackActive: boolean;
      gpsEffectiveSpeedKph: number | null;
      obdDeviceMac: string | null;
      obdDeviceName: string | null;
    } = {
      gpsFallbackActive: deps.settings.speed.gpsFallbackActive.value,
      gpsEffectiveSpeedKph: deps.settings.speed.gpsEffectiveSpeedKph.value,
      manualSpeedKph: deps.settings.speed.manualSpeedKph.value,
      obdDeviceMac: deps.settings.speed.obdDeviceMac.value,
      obdDeviceName: deps.settings.speed.obdDeviceName.value,
      resolvedSpeedSource: deps.settings.speed.resolvedSource.value,
      speedSource: deps.settings.speed.source.value,
    };
    return {
      diagnosticsOpen: diagnosticsOpen.value,
      draftDirty: selectedModeDraft.value !== null,
      manualSpeedFeedback: cloneFeedback(manualSpeedFeedback.value),
      manualSpeedInputValue: manualSpeedInputValue.value,
      obdScanStatusMessage: obdScanStatusMessage.value,
      obdSelectionError: obdSelectionError.value,
      pairInFlightMac: pairInFlightMac.value,
      saveFeedback: cloneFeedback(saveFeedback.value),
      scannedDevices: [...scannedDevices.value],
      scanInFlight: scanInFlight.value,
      selectedMode: selectedMode.value,
      settings: settingsSnapshot,
      staleTimeoutFeedback: cloneFeedback(staleTimeoutFeedback.value),
      staleTimeoutInputValue: staleTimeoutInputValue.value,
    };
  });

  function getRenderState(): SettingsSpeedSourceRenderState {
    return renderState.value;
  }

  function shouldRunBackgroundRescan(): boolean {
    return backgroundRescanRequested.value
      && speedSourceContextVisible.value
      && selectedMode.value === "obd2"
      && !scanInFlight.value
      && pairInFlightMac.value === null;
  }

  function syncContextVisibility(): void {
    speedSourceContextVisible.value = deps.obdConfigVisible.value;
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
      selectedModeDraft.value = null;
      manualSpeedInputDraft.value = null;
      manualSpeedFeedback.value = null;
      staleTimeoutFeedback.value = null;
      saveFeedback.value = null;
      obdSelectionError.value = false;
    });
    scheduleContextVisibilitySync();
  }

  function syncFromSettings(): void {
    scheduleContextVisibilitySync();
  }

  function applyPayload(
    payload: SpeedSourcePayload,
    options: { preserveResolvedSource?: boolean } = {},
  ): void {
    batch(() => {
      deps.settings.speed.source.value = payload.speed_source;
      deps.settings.speed.manualSpeedKph.value = payload.manual_speed_kph;
      deps.settings.speed.obdDeviceMac.value = payload.obd_device_mac ?? null;
      deps.settings.speed.obdDeviceName.value = payload.obd_device_name ?? null;
      if (!options.preserveResolvedSource) {
        deps.settings.speed.resolvedSource.value = null;
      }
      staleTimeoutInputValue.value = String(payload.stale_timeout_s);
      syncInputsFromSettings();
    });
  }

  async function loadSpeedSourceFromServer(): Promise<void> {
    const payload = await deps.queryClient.fetchQuery({
      queryFn: () => transport.loadSpeedSource(),
      queryKey: serverStateQueryKeys.settings.speedSource(),
      staleTime: 0,
    });
    applyPayload(payload, { preserveResolvedSource: true });
  }

  function handleSpeedSourceChanged(mode: DisplayedSpeedSourceMode): void {
    batch(() => {
      selectedModeDraft.value = mode;
      clearAllFeedback();
    });
    scheduleContextVisibilitySync();
  }

  function handleManualSpeedInput(value: string): void {
    batch(() => {
      manualSpeedInputDraft.value = value;
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

    const source: SpeedSourceKind =
      selectedModeDraft.value ?? deps.settings.speed.source.value;
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

    if (source === "obd2" && !deps.settings.speed.obdDeviceMac.value) {
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
      deps.queryClient.setQueryData(serverStateQueryKeys.settings.speedSource(), saved);
      await deps.queryClient.invalidateQueries({ queryKey: serverStateQueryKeys.settings.gpsStatus() });
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
    try {
      const payload = await deps.queryClient.fetchQuery({
        queryFn: () => transport.scanObdDevices(),
        queryKey: serverStateQueryKeys.settings.speedSourceObdScan(),
        staleTime: 0,
      });
      if (mode === "manual") {
        backgroundRescanRequested.value = true;
        batch(() => {
          setScannedDevices(payload.devices);
          obdScanStatusMessage.value = payload.devices.length > 0
            ? deps.t("settings.speed.obd_scan_found", { count: payload.devices.length })
            : deps.t("settings.speed.obd_scan_empty");
        });
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
    }
  }

  async function pairObdDevice(macAddress: string): Promise<void> {
    clearObdSelectionFeedback();
    batch(() => {
      pairInFlightMac.value = macAddress;
      obdScanStatusMessage.value = deps.t("settings.speed.obd_pairing");
    });
    try {
      const payload = await transport.pairObdDevice(macAddress);
      batch(() => {
        deps.settings.speed.obdDeviceMac.value = payload.configured_device_mac ?? null;
        deps.settings.speed.obdDeviceName.value = payload.configured_device_name ?? null;
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
      await deps.queryClient.invalidateQueries({
        queryKey: serverStateQueryKeys.settings.gpsStatus(),
      });
    } catch (error) {
      obdScanStatusMessage.value = deps.t("settings.speed.obd_pair_failed");
      deps.showError(error instanceof Error ? error.message : deps.t("settings.speed.obd_pair_failed"));
    } finally {
      pairInFlightMac.value = null;
    }
  }

  function handleNavigateContext(): void {
    syncContextVisibility();
  }

  const obdBackgroundRescanEnabled = computed(() => shouldRunBackgroundRescan());

  const obdBackgroundRescan = createObservedServerStateQuery({
    enabled: obdBackgroundRescanEnabled,
    observerOptions: {
      refetchInterval: OBD_BACKGROUND_RESCAN_DELAY_MS,
      refetchIntervalInBackground: true,
    },
    onData: (payload) => {
      mergeScannedDevices(payload.devices);
    },
    queryClient: deps.queryClient,
    queryFn: () => transport.scanObdDevices(),
    queryKey: serverStateQueryKeys.settings.speedSourceObdScan(),
  });

  return {
    dispose(): void {
      obdBackgroundRescan.dispose();
    },
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

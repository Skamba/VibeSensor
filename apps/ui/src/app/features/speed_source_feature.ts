import type { QueryClient } from "@tanstack/query-core";

import {
  getSettingsObdStatus,
  getSettingsSpeedSource,
  getSpeedSourceStatus,
  pairSettingsObdDevice,
  scanSettingsObdDevices,
  updateSettingsSpeedSource,
} from "../../api/settings";
import type {
  ObdDevicePayload,
  ObdScanPayload,
  ObdStatusPayload,
  SpeedSourceKind,
  SpeedSourcePayload,
  SpeedSourceRequest,
  SpeedSourceStatusPayload,
} from "../../api/types";
import { GPS_POLL_FAST_MS, GPS_POLL_SLOW_MS } from "../../config";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { SettingsState } from "../settings_state";
import {
  createSpeedSourceDerivedState,
  type DisplayedSpeedSourceMode,
} from "../speed_source_state";
import {
  batch,
  computed,
  effectOnChange,
  signal,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";
import type { Feedback } from "../../components/feedback";
import {
  activeSpeedSourceLabel,
  buildSettingsSpeedSourcePanelModel,
  buildSpeedSourceDiagnosticsRenderModel,
  DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL,
  hasHumanReadableObdDeviceName,
  type SettingsSpeedSourceRenderState,
} from "../views/settings_speed_source_presenter";
import type { SpeedSourcePanelView } from "../views/speed_source_panel";
import { applySpeedSourcePayloadToSettings } from "./dashboard_startup_state";
import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "./server_state_query";
import { serverStateQueryKeys } from "./server_state_query_keys";
import { applySpeedSourceStatusToSettings } from "./speed_source_status_state";
import { createWorkflowGenerationGuard } from "./workflow_generation_guard";

const OBD_BACKGROUND_RESCAN_DELAY_MS = 2_000;

interface GpsStatusSnapshot {
  obdStatus: ObdStatusPayload | null;
  status: SpeedSourceStatusPayload;
}

export interface SpeedSourceFeature {
  bindHandlers(): void;
  dispose(): void;
  handleManualSpeedInput(value: string): void;
  handleSpeedSourceChanged(mode: DisplayedSpeedSourceMode): void;
  handleStaleTimeoutInput(value: string): void;
  /** Loads the saved speed source, then starts the tab's GPS/OBD status polling. */
  loadSpeedSourceFromServer(): Promise<void>;
  pairObdDevice(macAddress: string): Promise<void>;
  readonly renderState: ReadonlySignal<SettingsSpeedSourceRenderState>;
  saveSpeedSource(): Promise<void>;
  scanObdDevices(): Promise<void>;
}

function parseManualSpeedKph(rawValue: number): number | null {
  return Number.isFinite(rawValue) && rawValue > 0 && rawValue <= 500
    ? rawValue
    : null;
}

function compareScannedDevices(
  left: ObdDevicePayload,
  right: ObdDevicePayload,
): number {
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
  const leftNamedRank = Number(!hasHumanReadableObdDeviceName(left));
  const rightNamedRank = Number(!hasHumanReadableObdDeviceName(right));
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

function cloneFeedback(message: Feedback | null): Feedback | null {
  return message ? { ...message } : null;
}

/**
 * Speed-source settings controller: owns the draft/validation/save flow, OBD
 * scan/pair actions with background rescans, and the tab's GPS/OBD status
 * polling behind the typed `SpeedSourcePanelView` bridge.
 */
export function createSpeedSourceFeature(ctx: {
  panel: SpeedSourcePanelView;
  settings: SettingsState;
  queryClient: QueryClient;
  services: Pick<FeatureServices, "t" | "showError">;
  formatting: Pick<FeatureFormatting, "fmt">;
  getSpeedUnit: () => string;
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
}): SpeedSourceFeature {
  const { settings, queryClient, panel } = ctx;
  const { t, showError } = ctx.services;
  const presenterDeps = {
    fmt: ctx.formatting.fmt,
    getSpeedUnit: ctx.getSpeedUnit,
    t,
  };
  const speedTabVisible = computed(
    () =>
      ctx.activeViewId.value === "settingsView" &&
      ctx.activeSettingsTabId.value === "speedSourceTab",
  );

  // ---------------------------------------------------------------------
  // Draft, validation, and save state
  // ---------------------------------------------------------------------

  const speedSourceState = createSpeedSourceDerivedState(settings.speed);
  const selectedModeDraft = signal<DisplayedSpeedSourceMode | null>(null);
  const manualSpeedInputDraft = signal<string | null>(null);
  const selectedMode = computed<DisplayedSpeedSourceMode>(
    () => selectedModeDraft.value ?? speedSourceState.displayedMode.value,
  );
  const manualSpeedInputValue = computed(() => {
    const draft = manualSpeedInputDraft.value;
    if (draft != null) {
      return draft;
    }
    return settings.speed.manualSpeedKph.value != null
      ? String(settings.speed.manualSpeedKph.value)
      : "";
  });
  const staleTimeoutInputValue = signal("");
  const speedSourceContextVisible = signal(false);
  const backgroundRescanRequested = signal(false);
  const scannedDevices = signal<readonly ObdDevicePayload[]>([]);
  const scanInFlight = signal(false);
  const pairInFlightMac = signal<string | null>(null);
  const obdScanStatusMessage = signal<string | null>(null);
  const manualSpeedFeedback = signal<Feedback | null>(null);
  const staleTimeoutFeedback = signal<Feedback | null>(null);
  const saveFeedback = signal<Feedback | null>(null);
  const obdSelectionError = signal(false);
  const diagnosticsOpen = signal(false);
  let disposed = false;
  let handlersBound = false;
  let disposeNavigationContextSync: (() => void) | null = null;
  const isActive = () => !disposed;
  const loadRequests = createWorkflowGenerationGuard({ isActive });
  const saveRequests = createWorkflowGenerationGuard({ isActive });
  const scanRequests = createWorkflowGenerationGuard({ isActive });
  const pairRequests = createWorkflowGenerationGuard({ isActive });
  let saveInFlight = false;

  const renderState = computed<SettingsSpeedSourceRenderState>(() => ({
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
    settings: {
      gpsFallbackActive: settings.speed.gpsFallbackActive.value,
      gpsEffectiveSpeedKph: settings.speed.gpsEffectiveSpeedKph.value,
      manualSpeedKph: settings.speed.manualSpeedKph.value,
      obdDeviceMac: settings.speed.obdDeviceMac.value,
      obdDeviceName: settings.speed.obdDeviceName.value,
      resolvedSpeedSource: settings.speed.resolvedSource.value,
      speedSource: settings.speed.source.value,
    },
    staleTimeoutFeedback: cloneFeedback(staleTimeoutFeedback.value),
    staleTimeoutInputValue: staleTimeoutInputValue.value,
  }));
  panel.model.value = computed(() =>
    buildSettingsSpeedSourcePanelModel(renderState.value, presenterDeps),
  );

  // The OBD config is "in context" only while the speed tab is visible with
  // OBD selected. It is re-read on navigation, draft, and status changes (not
  // continuously) so background rescans follow those transitions.
  function syncContextVisibility(): void {
    speedSourceContextVisible.value =
      speedTabVisible.value && selectedMode.value === "obd2";
  }

  let contextSyncScheduled = false;
  function scheduleContextVisibilitySync(): void {
    if (contextSyncScheduled) {
      return;
    }
    contextSyncScheduled = true;
    queueMicrotask(() => {
      contextSyncScheduled = false;
      if (!disposed) {
        syncContextVisibility();
      }
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

  function clearObdSelectionFeedback(): void {
    batch(() => {
      obdSelectionError.value = false;
      saveFeedback.value = null;
    });
  }

  function showSaveFeedback(message: string, detail: string): void {
    batch(() => {
      saveFeedback.value = {
        body: message,
        detail,
        title: t("settings.speed.save_failed_title"),
        tone: "error",
      };
      diagnosticsOpen.value = true;
    });
  }

  function setScannedDevices(devices: readonly ObdDevicePayload[]): void {
    scannedDevices.value = [...devices].sort(compareScannedDevices);
  }

  function mergeScannedDevices(devices: readonly ObdDevicePayload[]): void {
    const merged = new Map(
      scannedDevices.value.map((device) => [device.mac_address, device]),
    );
    for (const device of devices) {
      merged.set(device.mac_address, device);
    }
    setScannedDevices(Array.from(merged.values()));
  }

  function applyPayload(
    payload: SpeedSourcePayload,
    options: { preserveResolvedSource?: boolean } = {},
  ): void {
    batch(() => {
      applySpeedSourcePayloadToSettings(settings.speed, payload, options);
      staleTimeoutInputValue.value = String(payload.stale_timeout_s);
      // Saved/loaded settings replace any local drafts and feedback.
      selectedModeDraft.value = null;
      manualSpeedInputDraft.value = null;
      clearAllFeedback();
    });
    scheduleContextVisibilitySync();
  }

  async function loadSavedSpeedSource(): Promise<void> {
    if (disposed) {
      return;
    }
    const requestGeneration = loadRequests.begin();
    let payload: SpeedSourcePayload;
    try {
      payload = await queryClient.fetchQuery({
        queryFn: () => getSettingsSpeedSource(),
        queryKey: serverStateQueryKeys.settings.speedSource(),
        staleTime: 0,
      });
    } catch (error) {
      if (!loadRequests.isCurrent(requestGeneration)) {
        return;
      }
      throw error;
    }
    if (loadRequests.isCurrent(requestGeneration)) {
      applyPayload(payload, { preserveResolvedSource: true });
    }
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
      manualSpeedFeedback.value = null;
      saveFeedback.value = null;
    });
  }

  function handleStaleTimeoutInput(value: string): void {
    batch(() => {
      staleTimeoutInputValue.value = value;
      staleTimeoutFeedback.value = null;
      saveFeedback.value = null;
    });
  }

  async function saveSpeedSource(): Promise<void> {
    if (disposed || saveInFlight) {
      return;
    }
    clearAllFeedback();

    const source: SpeedSourceKind =
      selectedModeDraft.value ?? settings.speed.source.value;
    const manualInputValue = manualSpeedInputValue.value.trim();
    const manualSpeedKph = parseManualSpeedKph(Number(manualInputValue));
    const staleValueRaw = staleTimeoutInputValue.value.trim();
    const staleValue = Number(staleValueRaw);
    const staleTimeoutInvalid =
      source !== "manual" &&
      (staleValueRaw === "" ||
        Number.isNaN(staleValue) ||
        !Number.isFinite(staleValue) ||
        staleValue < 3 ||
        staleValue > 120);
    const manualSpeedInvalid =
      (source === "manual" && manualSpeedKph == null) ||
      (manualInputValue !== "" && manualSpeedKph == null);
    const activeSource = activeSpeedSourceLabel(renderState.value.settings, t);
    const validationDetail = t("settings.speed.validation_active_detail", {
      source: activeSource,
    });

    if (manualSpeedInvalid) {
      batch(() => {
        manualSpeedFeedback.value = {
          body: t("settings.speed.manual_invalid"),
          compact: true,
          tone: "error",
        };
        showSaveFeedback(t("settings.speed.manual_invalid"), validationDetail);
      });
      panel.focusManualSpeedInput();
      return;
    }

    if (staleTimeoutInvalid) {
      batch(() => {
        staleTimeoutFeedback.value = {
          body: t("settings.speed.stale_timeout_invalid"),
          compact: true,
          tone: "error",
        };
        showSaveFeedback(
          t("settings.speed.stale_timeout_invalid"),
          validationDetail,
        );
      });
      panel.focusStaleTimeoutInput();
      return;
    }

    if (source === "obd2" && !settings.speed.obdDeviceMac.value) {
      batch(() => {
        obdSelectionError.value = true;
        showSaveFeedback(
          t("settings.speed.obd_missing_device_error"),
          validationDetail,
        );
      });
      panel.focusScanObdDevices();
      return;
    }

    saveInFlight = true;
    const requestGeneration = saveRequests.begin();
    const payload: SpeedSourceRequest = {
      manual_speed_kph: manualSpeedKph,
      speed_source: source,
    };
    if (staleValue >= 3 && staleValue <= 120) {
      payload.stale_timeout_s = staleValue;
    }

    try {
      const saved = await updateSettingsSpeedSource(payload);
      if (!saveRequests.isCurrent(requestGeneration)) {
        return;
      }
      queryClient.setQueryData(
        serverStateQueryKeys.settings.speedSource(),
        saved,
      );
      await queryClient.invalidateQueries({
        queryKey: serverStateQueryKeys.settings.gpsStatus(),
      });
      if (!saveRequests.isCurrent(requestGeneration)) {
        return;
      }
      applyPayload(saved);
    } catch (error) {
      if (!saveRequests.isCurrent(requestGeneration)) {
        return;
      }
      showSaveFeedback(
        error instanceof Error ? error.message : t("settings.save_failed"),
        t("settings.speed.save_failed_detail", { source: activeSource }),
      );
    } finally {
      if (saveRequests.isLatest(requestGeneration)) {
        saveInFlight = false;
      }
    }
  }

  // ---------------------------------------------------------------------
  // OBD scan / pair
  // ---------------------------------------------------------------------

  function fetchObdScan(): Promise<ObdScanPayload> {
    return queryClient.fetchQuery({
      queryFn: () => scanSettingsObdDevices(),
      queryKey: serverStateQueryKeys.settings.speedSourceObdScan(),
      staleTime: 0,
    });
  }

  async function scanObdDevices(): Promise<void> {
    if (disposed || scanInFlight.value || pairInFlightMac.value !== null) {
      return;
    }
    const requestGeneration = scanRequests.begin();
    batch(() => {
      scanInFlight.value = true;
      clearObdSelectionFeedback();
      obdScanStatusMessage.value = t("settings.speed.obd_scanning");
    });
    try {
      const payload = await fetchObdScan();
      if (!scanRequests.isCurrent(requestGeneration)) {
        return;
      }
      backgroundRescanRequested.value = true;
      batch(() => {
        setScannedDevices(payload.devices);
        obdScanStatusMessage.value =
          payload.devices.length > 0
            ? t("settings.speed.obd_scan_found", {
                count: payload.devices.length,
              })
            : t("settings.speed.obd_scan_empty");
      });
    } catch (error) {
      if (!scanRequests.isCurrent(requestGeneration)) {
        return;
      }
      obdScanStatusMessage.value = t("settings.speed.obd_scan_failed");
      showError(
        error instanceof Error
          ? error.message
          : t("settings.speed.obd_scan_failed"),
      );
    } finally {
      if (scanRequests.isCurrent(requestGeneration)) {
        scanInFlight.value = false;
      }
    }
  }

  async function pairObdDevice(macAddress: string): Promise<void> {
    if (disposed || pairInFlightMac.value !== null) {
      return;
    }
    const requestGeneration = pairRequests.begin();
    clearObdSelectionFeedback();
    batch(() => {
      pairInFlightMac.value = macAddress;
      obdScanStatusMessage.value = t("settings.speed.obd_pairing");
    });
    try {
      const payload = await pairSettingsObdDevice(macAddress);
      if (!pairRequests.isCurrent(requestGeneration)) {
        return;
      }
      batch(() => {
        settings.speed.obdDeviceMac.value =
          payload.configured_device_mac ?? null;
        settings.speed.obdDeviceName.value =
          payload.configured_device_name ?? null;
        mergeScannedDevices([
          {
            connected: payload.connected,
            mac_address: payload.configured_device_mac ?? macAddress,
            name: payload.configured_device_name ?? null,
            paired: payload.paired,
            rfcomm_channel: payload.rfcomm_channel,
            trusted: payload.trusted,
          },
        ]);
        obdScanStatusMessage.value = t("settings.speed.obd_pair_success");
      });
      await queryClient.invalidateQueries({
        queryKey: serverStateQueryKeys.settings.gpsStatus(),
      });
    } catch (error) {
      if (!pairRequests.isCurrent(requestGeneration)) {
        return;
      }
      obdScanStatusMessage.value = t("settings.speed.obd_pair_failed");
      showError(
        error instanceof Error
          ? error.message
          : t("settings.speed.obd_pair_failed"),
      );
    } finally {
      if (pairRequests.isCurrent(requestGeneration)) {
        pairInFlightMac.value = null;
      }
    }
  }

  // While OBD is in context after a manual scan, keep merging rescans in the
  // background so newly advertising adapters show up.
  const obdBackgroundRescan = createObservedServerStateQuery({
    enabled: computed(
      () =>
        backgroundRescanRequested.value &&
        speedSourceContextVisible.value &&
        selectedMode.value === "obd2" &&
        !scanInFlight.value &&
        pairInFlightMac.value === null,
    ),
    observerOptions: createHiddenTabPollingObserverOptions<
      ObdScanPayload,
      ReturnType<typeof serverStateQueryKeys.settings.speedSourceObdScan>
    >(OBD_BACKGROUND_RESCAN_DELAY_MS),
    onData: (payload) => {
      if (!disposed) {
        mergeScannedDevices(payload.devices);
      }
    },
    queryClient,
    queryFn: () => scanSettingsObdDevices(),
    queryKey: serverStateQueryKeys.settings.speedSourceObdScan(),
  });

  // ---------------------------------------------------------------------
  // GPS / OBD status diagnostics polling
  // ---------------------------------------------------------------------

  const gpsHandlersBound = signal(false);
  const gpsStartupReady = signal(false);
  const diagnosticsModel = signal(DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL);
  panel.diagnostics.value = diagnosticsModel;
  const gpsStatusQuery = createObservedServerStateQuery<GpsStatusSnapshot>({
    enabled: computed(
      () =>
        gpsHandlersBound.value &&
        gpsStartupReady.value &&
        speedTabVisible.value,
    ),
    observerOptions: createHiddenTabPollingObserverOptions<GpsStatusSnapshot>(
      (query) =>
        query.state.data?.status.connection_state === "connected"
          ? GPS_POLL_FAST_MS
          : GPS_POLL_SLOW_MS,
    ),
    onData: ({ status, obdStatus }) => {
      batch(() => {
        applySpeedSourceStatusToSettings(settings.speed, status);
        diagnosticsModel.value = buildSpeedSourceDiagnosticsRenderModel(
          status,
          obdStatus,
          presenterDeps,
        );
      });
      scheduleContextVisibilitySync();
    },
    queryClient,
    queryFn: async () => {
      const shouldLoadObdStatus =
        settings.speed.source.value === "obd2" ||
        settings.speed.obdDeviceMac.value != null;
      const [status, obdStatus] = await Promise.all([
        getSpeedSourceStatus(),
        shouldLoadObdStatus ? getSettingsObdStatus() : Promise.resolve(null),
      ]);
      return { obdStatus, status };
    },
    queryKey: serverStateQueryKeys.settings.gpsStatus(),
  });

  return {
    bindHandlers(): void {
      if (handlersBound) {
        return;
      }
      handlersBound = true;
      disposeNavigationContextSync = effectOnChange(
        computed(
          () => `${ctx.activeViewId.value}::${ctx.activeSettingsTabId.value}`,
        ),
        () => {
          untracked(syncContextVisibility);
        },
      );
      panel.actions.value = {
        onManualSpeedInput: handleManualSpeedInput,
        onPairObdDevice(macAddress): void {
          void pairObdDevice(macAddress);
        },
        onSave(): void {
          void saveSpeedSource();
        },
        onScanObdDevices(): void {
          void scanObdDevices();
        },
        onSpeedSourceChanged: handleSpeedSourceChanged,
        onStaleTimeoutInput: handleStaleTimeoutInput,
      };
      syncContextVisibility();
      gpsHandlersBound.value = true;
    },
    dispose(): void {
      disposeNavigationContextSync?.();
      disposeNavigationContextSync = null;
      disposed = true;
      loadRequests.invalidate();
      saveRequests.invalidate();
      scanRequests.invalidate();
      pairRequests.invalidate();
      saveInFlight = false;
      obdBackgroundRescan.dispose();
      gpsStatusQuery.dispose();
    },
    handleManualSpeedInput,
    handleSpeedSourceChanged,
    handleStaleTimeoutInput,
    async loadSpeedSourceFromServer(): Promise<void> {
      try {
        await loadSavedSpeedSource();
      } finally {
        gpsStartupReady.value = true;
        await gpsStatusQuery
          .fetch()
          .then(() => undefined)
          .catch(() => undefined);
      }
    },
    pairObdDevice,
    renderState,
    saveSpeedSource,
    scanObdDevices,
  };
}

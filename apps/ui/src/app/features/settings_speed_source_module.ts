import type {
  ObdDevicePayload,
  SpeedSourceKind,
  SpeedSourcePayload,
  SpeedSourceRequest,
} from "../../transport/http_models";
import {
  getSettingsSpeedSource,
  pairSettingsObdDevice,
  scanSettingsObdDevices,
  updateSettingsSpeedSource,
} from "../../api";
import type { UiSettingsDom } from "../dom/settings_dom";
import type { UiShellDom } from "../dom/shell_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import { createPollingController } from "./polling_controller";
import { setSettingsFeedback } from "../views/settings_feedback";
import {
  bindSettingsSpeedSourceInteractions,
  type SettingsSpeedSourceInteraction,
} from "../views/settings_speed_source_bindings";
import {
  type DisplayedSpeedSourceMode,
  deriveDisplayedSpeedSourceMode,
  isManualLikeSpeedSource,
  resolveEffectiveSpeedSource,
} from "../speed_source_state";
import type { SettingsState } from "../ui_app_state";

const SPEED_SOURCE_KINDS = ["gps", "manual", "obd2"] as const satisfies readonly SpeedSourceKind[];
const OBD_BACKGROUND_RESCAN_DELAY_MS = 2_000;

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
  dom: UiSettingsDom;
  shellDom: Pick<UiShellDom, "menuButtons">;
  settings: SettingsState;
  getSpeedUnit: () => string;
  fmt: (n: number, digits?: number) => string;
  renderSpeedReadout: () => void;
  onSaveError: (error: unknown) => void;
}

export interface SettingsSpeedSourceModule {
  bindHandlers(): void;
  syncSpeedSourceSelectionUi(): void;
  syncSpeedSourceInputs(): void;
  loadSpeedSourceFromServer(): Promise<void>;
  saveSpeedSourceFromInputs(): void;
}

export function createSettingsSpeedSourceModule(ctx: SettingsSpeedSourceModuleDeps): SettingsSpeedSourceModule {
  const { settings, dom: els, shellDom, t, escapeHtml } = ctx;
  let speedSourceDraftDirty = false;
  let obdScanStatusMessage: string | null = null;
  let scannedDevices: ObdDevicePayload[] = [];
  let scanInFlight = false;
  let pairInFlightMac: string | null = null;
  let backgroundRescanRequested = false;

  function isSpeedSourceKind(value: string): value is SpeedSourceKind {
    return SPEED_SOURCE_KINDS.some((kind) => kind === value);
  }

  function parseManualSpeedKph(rawValue: number): number | null {
    return Number.isFinite(rawValue) && rawValue > 0 && rawValue <= 500 ? rawValue : null;
  }

  function applyStaleTimeoutFromInput(payload: SpeedSourceRequest): void {
    const staleVal = Number(els.staleTimeoutInput?.value);
    if (staleVal >= 3 && staleVal <= 120) payload.stale_timeout_s = staleVal;
  }

  function clearInputFeedback(input: HTMLInputElement | null, feedback: HTMLElement | null): void {
    input?.removeAttribute("aria-invalid");
    input?.removeAttribute("aria-describedby");
    setSettingsFeedback(feedback, null);
  }

  function showInputFeedback(input: HTMLInputElement | null, feedback: HTMLElement | null, message: string): void {
    if (feedback?.id) {
      input?.setAttribute("aria-describedby", feedback.id);
    }
    input?.setAttribute("aria-invalid", "true");
    setSettingsFeedback(feedback, {
      tone: "error",
      body: message,
      compact: true,
    });
    input?.focus();
  }

  function clearSpeedSourceFeedback(): void {
    clearInputFeedback(els.manualSpeedInput, els.manualSpeedFeedback);
    clearInputFeedback(els.staleTimeoutInput, els.staleTimeoutFeedback);
    els.speedSourceChoiceObd?.classList.remove("speed-source-choice--error");
    els.speedSourceRadios.forEach((radio) => {
      radio.removeAttribute("aria-invalid");
    });
    setSettingsFeedback(els.speedSourceSaveFeedback, null);
  }

  function clearObdSelectionFeedback(): void {
    els.speedSourceChoiceObd?.classList.remove("speed-source-choice--error");
    els.speedSourceRadios.find((radio) => radio.value === "obd2")?.removeAttribute("aria-invalid");
    setSettingsFeedback(els.speedSourceSaveFeedback, null);
  }

  function openSpeedSourceDiagnostics(): void {
    els.speedSourceDiagnostics?.setAttribute("open", "");
  }

  function showSpeedSourceSaveFeedback(message: string, detail: string): void {
    setSettingsFeedback(els.speedSourceSaveFeedback, {
      tone: "error",
      title: t("settings.speed.save_failed_title"),
      body: message,
      detail,
    });
    openSpeedSourceDiagnostics();
  }

  function selectedSpeedUnitLabel(): string {
    return ctx.getSpeedUnit() === "mps" ? t("speed.unit.mps") : t("speed.unit.kmh");
  }

  function speedKphInSelectedUnit(speedKmh: number | null): number | null {
    if (speedKmh === null || !Number.isFinite(speedKmh)) return null;
    return ctx.getSpeedUnit() === "mps" ? speedKmh / 3.6 : speedKmh;
  }

  function formatSpeedValue(speedKmh: number | null): string {
    const speed = speedKphInSelectedUnit(speedKmh);
    return speed != null ? `${ctx.fmt(speed, 1)} ${selectedSpeedUnitLabel()}` : "--";
  }

  function formatConfiguredObdDevice(): string {
    if (settings.obdDeviceName && settings.obdDeviceMac) {
      return `${settings.obdDeviceName} (${settings.obdDeviceMac})`;
    }
    return settings.obdDeviceName ?? settings.obdDeviceMac ?? t("settings.speed.obd_not_configured");
  }

  function activeSourceLabel(): string {
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

  function activeEffectiveSpeedKph(): number | null {
    return isManualLikeSpeedSource(resolveEffectiveSpeedSource(settings))
      ? settings.manualSpeedKph
      : settings.gpsEffectiveSpeedKph;
  }

  function applyDisplayedModeToRadios(displayedMode: DisplayedSpeedSourceMode): void {
    els.speedSourceRadios.forEach((radio) => {
      radio.checked = radio.value === displayedMode;
    });
  }

  function syncChoiceState(
    element: HTMLElement | null,
    { active, pending }: { active: boolean; pending: boolean },
  ): void {
    if (!element) {
      return;
    }
    element.classList.toggle("speed-source-choice--active", active);
    element.classList.toggle("speed-source-choice--selected", active);
    element.classList.toggle("speed-source-choice--draft", pending);
    if (pending) {
      element.setAttribute("data-choice-badge", t("settings.speed.choice_pending"));
      return;
    }
    if (active) {
      element.setAttribute("data-choice-badge", t("settings.speed.choice_active"));
      return;
    }
    element.removeAttribute("data-choice-badge");
  }

  function selectedSpeedSourceMode(): DisplayedSpeedSourceMode {
    const checkedRadio = els.speedSourceRadios.find((radio) => radio.checked);
    if (checkedRadio?.value === "obd2") return "obd2";
    if (checkedRadio?.value === "manual") return "manual";
    if (checkedRadio?.value === "gps") return "gps";
    return deriveDisplayedSpeedSourceMode(settings);
  }

  function updateSpeedSourceSummary(): void {
    if (els.speedSourceCurrentSource) {
      els.speedSourceCurrentSource.textContent = activeSourceLabel();
    }
    if (els.speedSourceEffectiveSpeed) {
      els.speedSourceEffectiveSpeed.textContent = formatSpeedValue(activeEffectiveSpeedKph());
    }
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
    const labelCompare = (left.name?.trim() || left.mac_address).localeCompare(
      right.name?.trim() || right.mac_address,
    );
    if (labelCompare !== 0) {
      return labelCompare;
    }
    return left.mac_address.localeCompare(right.mac_address);
  }

  function setScannedDevices(devices: readonly ObdDevicePayload[]): void {
    scannedDevices = [...devices].sort(compareScannedDevices);
  }

  function mergeScannedDevices(devices: readonly ObdDevicePayload[]): void {
    const merged = new Map(scannedDevices.map((device) => [device.mac_address, device]));
    devices.forEach((device) => {
      merged.set(device.mac_address, device);
    });
    setScannedDevices(Array.from(merged.values()));
  }

  function isObdConfigVisible(): boolean {
    if (!els.obdSpeedConfig || els.obdSpeedConfig.hidden) {
      return false;
    }
    const activePanel = els.obdSpeedConfig.closest<HTMLElement>(".settings-tab-panel");
    if (!activePanel || activePanel.hidden) {
      return false;
    }
    const activeView = activePanel.closest<HTMLElement>(".view");
    return activeView == null || !activeView.hidden;
  }

  function shouldRunBackgroundRescan(): boolean {
    return backgroundRescanRequested && isObdConfigVisible();
  }

  function syncObdBackgroundRescan(): void {
    if (shouldRunBackgroundRescan()) {
      obdBackgroundRescan.start();
      return;
    }
    obdBackgroundRescan.stop();
  }

  function scheduleObdBackgroundRescanSync(): void {
    queueMicrotask(syncObdBackgroundRescan);
  }

  function obdDevicePrimaryLabel(device: ObdDevicePayload): string {
    return device.name?.trim() || device.mac_address;
  }

  function obdDeviceSecondaryLabel(device: ObdDevicePayload): string | null {
    return device.name?.trim() ? device.mac_address : null;
  }

  function renderObdDeviceList(): void {
    if (!els.obdDeviceList) {
      return;
    }
    if (scannedDevices.length === 0) {
      els.obdDeviceList.innerHTML = "";
      return;
    }
    els.obdDeviceList.innerHTML = scannedDevices.map((device) => {
      const badges: string[] = [];
      if (device.mac_address === settings.obdDeviceMac) {
        badges.push(
          `<span class="speed-source-device__badge speed-source-device__badge--active">${escapeHtml(t("settings.speed.obd_configured_badge"))}</span>`,
        );
      }
      if (device.paired) {
        badges.push(`<span class="speed-source-device__badge">${escapeHtml(t("settings.speed.obd_paired_badge"))}</span>`);
      }
      if (device.trusted) {
        badges.push(`<span class="speed-source-device__badge">${escapeHtml(t("settings.speed.obd_trusted_badge"))}</span>`);
      }
      if (device.connected) {
        badges.push(
          `<span class="speed-source-device__badge speed-source-device__badge--active">${escapeHtml(t("settings.speed.obd_connected_badge"))}</span>`,
        );
      }
      const actionLabel = pairInFlightMac === device.mac_address
        ? t("settings.speed.obd_pairing")
        : device.paired && device.trusted
          ? t("settings.speed.obd_use")
          : t("settings.speed.obd_pair_and_use");
      const secondaryLabel = obdDeviceSecondaryLabel(device);
      return `
        <div class="speed-source-device">
          <div class="speed-source-device__header">
            <div class="speed-source-device__identity">
              <div class="speed-source-device__name">${escapeHtml(obdDevicePrimaryLabel(device))}</div>
              ${secondaryLabel ? `<div class="speed-source-device__mac">${escapeHtml(secondaryLabel)}</div>` : ""}
            </div>
            <div class="speed-source-device__badges">${badges.join("")}</div>
          </div>
          <div class="speed-source-device__actions">
            <button
              class="btn btn--secondary"
              type="button"
              data-obd-pair-mac="${escapeHtml(device.mac_address)}"
              ${scanInFlight || pairInFlightMac !== null ? "disabled" : ""}
            >${escapeHtml(actionLabel)}</button>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderObdControls(): void {
    if (els.obdConfiguredDevice) {
      els.obdConfiguredDevice.textContent = formatConfiguredObdDevice();
    }
    if (els.scanObdDevicesBtn) {
      els.scanObdDevicesBtn.disabled = scanInFlight || pairInFlightMac !== null;
    }
    if (els.obdDeviceScanStatus) {
      els.obdDeviceScanStatus.textContent = obdScanStatusMessage ?? t("settings.speed.obd_scan_idle");
    }
    renderObdDeviceList();
  }

  const obdBackgroundRescan = createPollingController({
    poll: async () => {
      if (!shouldRunBackgroundRescan() || scanInFlight || pairInFlightMac !== null) {
        return OBD_BACKGROUND_RESCAN_DELAY_MS;
      }
      await scanObdDevices("background");
      return OBD_BACKGROUND_RESCAN_DELAY_MS;
    },
    onErrorDelayMs: OBD_BACKGROUND_RESCAN_DELAY_MS,
  });

  function syncSpeedSourceSelectionUi(): void {
    const displayedMode = deriveDisplayedSpeedSourceMode(settings);
    if (!speedSourceDraftDirty) {
      applyDisplayedModeToRadios(displayedMode);
    }
    const selectedMode = selectedSpeedSourceMode();
    const hasPendingSelection = speedSourceDraftDirty && selectedMode !== displayedMode;
    syncChoiceState(els.speedSourceChoiceGps, {
      active: displayedMode === "gps",
      pending: hasPendingSelection && selectedMode === "gps",
    });
    syncChoiceState(els.speedSourceChoiceObd, {
      active: displayedMode === "obd2",
      pending: hasPendingSelection && selectedMode === "obd2",
    });
    syncChoiceState(els.speedSourceChoiceManual, {
      active: displayedMode === "manual",
      pending: hasPendingSelection && selectedMode === "manual",
    });
    if (els.manualSpeedConfig) {
      els.manualSpeedConfig.hidden = selectedMode !== "manual";
    }
    if (els.obdSpeedConfig) {
      els.obdSpeedConfig.hidden = selectedMode !== "obd2";
    }
    if (els.gpsFallbackPanel) {
      els.gpsFallbackPanel.hidden = selectedMode === "manual";
    }
    updateSpeedSourceSummary();
    renderObdControls();
    syncObdBackgroundRescan();
  }

  function syncSpeedSourceInputs(): void {
    speedSourceDraftDirty = false;
    clearSpeedSourceFeedback();
    applyDisplayedModeToRadios(deriveDisplayedSpeedSourceMode(settings));
    if (els.manualSpeedInput) {
      els.manualSpeedInput.value = settings.manualSpeedKph != null ? String(settings.manualSpeedKph) : "";
    }
    syncSpeedSourceSelectionUi();
  }

  function applySpeedSourcePayload(payload: SpeedSourcePayload): void {
    settings.speedSource = payload.speed_source;
    settings.manualSpeedKph = payload.manual_speed_kph;
    settings.obdDeviceMac = payload.obd_device_mac ?? null;
    settings.obdDeviceName = payload.obd_device_name ?? null;
    settings.resolvedSpeedSource = null;
    if (els.staleTimeoutInput) els.staleTimeoutInput.value = String(payload.stale_timeout_s);
    syncSpeedSourceInputs();
    ctx.renderSpeedReadout();
  }

  async function syncSpeedSourceToServer(payload: SpeedSourceRequest): Promise<void> {
    try {
      const saved = await updateSettingsSpeedSource(payload);
      applySpeedSourcePayload(saved);
    } catch (error) {
      showSpeedSourceSaveFeedback(
        error instanceof Error ? error.message : t("settings.save_failed"),
        t("settings.speed.save_failed_detail", { source: activeSourceLabel() }),
      );
    }
  }

  async function loadSpeedSourceFromServer(): Promise<void> {
    try {
      const payload = await getSettingsSpeedSource();
      applySpeedSourcePayload(payload);
    } catch (_err) { /* ignore */ }
  }

  async function scanObdDevices(mode: "manual" | "background" = "manual"): Promise<void> {
    if (scanInFlight || pairInFlightMac !== null) {
      return;
    }
    scanInFlight = true;
    if (mode === "manual") {
      obdScanStatusMessage = t("settings.speed.obd_scanning");
    }
    renderObdControls();
    try {
      const payload = await scanSettingsObdDevices();
      if (mode === "manual") {
        setScannedDevices(payload.devices);
        backgroundRescanRequested = true;
        obdScanStatusMessage = payload.devices.length > 0
          ? t("settings.speed.obd_scan_found", { count: payload.devices.length })
          : t("settings.speed.obd_scan_empty");
      } else {
        mergeScannedDevices(payload.devices);
      }
      renderObdControls();
    } catch (error) {
      if (mode === "manual") {
        obdScanStatusMessage = t("settings.speed.obd_scan_failed");
        renderObdControls();
        ctx.showError(error instanceof Error ? error.message : t("settings.speed.obd_scan_failed"));
      }
    } finally {
      scanInFlight = false;
      renderObdControls();
      syncObdBackgroundRescan();
    }
  }

  async function pairObdDevice(macAddress: string): Promise<void> {
    pairInFlightMac = macAddress;
    obdScanStatusMessage = t("settings.speed.obd_pairing");
    renderObdControls();
    try {
      const payload = await pairSettingsObdDevice(macAddress);
      settings.obdDeviceMac = payload.configured_device_mac ?? null;
      settings.obdDeviceName = payload.configured_device_name ?? null;
      mergeScannedDevices([{
        mac_address: payload.configured_device_mac ?? macAddress,
        name: payload.configured_device_name ?? null,
        paired: payload.paired,
        trusted: payload.trusted,
        connected: payload.connected,
        rfcomm_channel: payload.rfcomm_channel,
      }]);
      obdScanStatusMessage = t("settings.speed.obd_pair_success");
      syncSpeedSourceSelectionUi();
    } catch (error) {
      obdScanStatusMessage = t("settings.speed.obd_pair_failed");
      renderObdControls();
      ctx.showError(error instanceof Error ? error.message : t("settings.speed.obd_pair_failed"));
    } finally {
      pairInFlightMac = null;
      renderObdControls();
      syncObdBackgroundRescan();
    }
  }

  function saveSpeedSourceFromInputs(): void {
    clearSpeedSourceFeedback();
    const checkedRadio = els.speedSourceRadios.find((radio) => radio.checked);
    const src: SpeedSourceKind = speedSourceDraftDirty && checkedRadio && isSpeedSourceKind(checkedRadio.value)
      ? checkedRadio.value
      : settings.speedSource;
    const manualInputValue = els.manualSpeedInput?.value.trim() ?? "";
    const manualSpeedKph = parseManualSpeedKph(Number(manualInputValue));
    const staleValueRaw = els.staleTimeoutInput?.value.trim() ?? "";
    const staleValue = Number(staleValueRaw);
    const staleTimeoutInvalid = src !== "manual" && (
      staleValueRaw === ""
      || Number.isNaN(staleValue)
      || !Number.isFinite(staleValue)
      || staleValue < 3
      || staleValue > 120
    );
    const manualSpeedInvalid = (src === "manual" && manualSpeedKph == null)
      || (manualInputValue !== "" && manualSpeedKph == null);
    if (manualSpeedInvalid) {
      showInputFeedback(els.manualSpeedInput, els.manualSpeedFeedback, t("settings.speed.manual_invalid"));
      showSpeedSourceSaveFeedback(t("settings.speed.manual_invalid"), t("settings.speed.validation_active_detail", {
        source: activeSourceLabel(),
      }));
      return;
    }
    if (staleTimeoutInvalid) {
      showInputFeedback(els.staleTimeoutInput, els.staleTimeoutFeedback, t("settings.speed.stale_timeout_invalid"));
      showSpeedSourceSaveFeedback(t("settings.speed.stale_timeout_invalid"), t("settings.speed.validation_active_detail", {
        source: activeSourceLabel(),
      }));
      return;
    }
    if (src === "obd2" && !settings.obdDeviceMac) {
      els.speedSourceChoiceObd?.classList.add("speed-source-choice--error");
      els.speedSourceRadios.find((radio) => radio.value === "obd2")?.setAttribute("aria-invalid", "true");
      showSpeedSourceSaveFeedback(t("settings.speed.obd_missing_device_error"), t("settings.speed.validation_active_detail", {
        source: activeSourceLabel(),
      }));
      els.scanObdDevicesBtn?.focus();
      return;
    }
    const payload: SpeedSourceRequest = {
      speed_source: src,
      manual_speed_kph: manualSpeedKph,
    };
    applyStaleTimeoutFromInput(payload);
    void syncSpeedSourceToServer(payload);
  }

  function bindHandlers(): void {
    bindSettingsSpeedSourceInteractions(els, shellDom, {
      onAction: (action: SettingsSpeedSourceInteraction) => {
        if (action.type === "speed-source-changed") {
          speedSourceDraftDirty = true;
          clearSpeedSourceFeedback();
          syncSpeedSourceSelectionUi();
          return;
        }
        if (action.type === "manual-speed-input") {
          clearInputFeedback(els.manualSpeedInput, els.manualSpeedFeedback);
          setSettingsFeedback(els.speedSourceSaveFeedback, null);
          return;
        }
        if (action.type === "stale-timeout-input") {
          clearInputFeedback(els.staleTimeoutInput, els.staleTimeoutFeedback);
          setSettingsFeedback(els.speedSourceSaveFeedback, null);
          return;
        }
        if (action.type === "save") {
          saveSpeedSourceFromInputs();
          return;
        }
        if (action.type === "scan-obd-devices") {
          clearObdSelectionFeedback();
          void scanObdDevices();
          return;
        }
        if (action.type === "navigate-context") {
          scheduleObdBackgroundRescanSync();
          return;
        }
        clearObdSelectionFeedback();
        void pairObdDevice(action.macAddress);
      },
    });
  }

  return {
    bindHandlers,
    syncSpeedSourceSelectionUi,
    syncSpeedSourceInputs,
    loadSpeedSourceFromServer,
    saveSpeedSourceFromInputs,
  };
}

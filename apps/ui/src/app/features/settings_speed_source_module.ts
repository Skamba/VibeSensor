import type {
  ObdDevicePayload,
  SpeedSourceKind,
  SpeedSourcePayload,
  SpeedSourceRequest,
} from "../../api/types";
import {
  getSettingsSpeedSource,
  pairSettingsObdDevice,
  scanSettingsObdDevices,
  updateSettingsSpeedSource,
} from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import { createPollingController } from "./polling_controller";
import {
  type DisplayedSpeedSourceMode,
  deriveDisplayedSpeedSourceMode,
  isManualLikeSpeedSource,
  resolveEffectiveSpeedSource,
} from "../speed_source_state";
import type { SettingsState } from "../ui_app_state";

const SPEED_SOURCE_KINDS = ["gps", "manual", "obd2"] as const satisfies readonly SpeedSourceKind[];
const OBD_BACKGROUND_RESCAN_DELAY_MS = 2_000;
const TAB_NAVIGATION_KEYS = new Set(["Enter", " ", "ArrowRight", "ArrowLeft", "Home", "End"]);

export interface SettingsSpeedSourceModuleDeps extends FeatureDepsBase {
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
  const { settings, els, t, escapeHtml } = ctx;
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
      return t("settings.speed.manual");
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

  function obdBoolLabel(value: boolean): string {
    return value ? t("settings.speed.fallback_yes") : t("settings.speed.fallback_no");
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
    els.speedSourceChoiceGps?.classList.toggle("speed-source-choice--selected", selectedMode === "gps");
    els.speedSourceChoiceObd?.classList.toggle("speed-source-choice--selected", selectedMode === "obd2");
    els.speedSourceChoiceManual?.classList.toggle("speed-source-choice--selected", selectedMode === "manual");
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
      void loadSpeedSourceFromServer();
      ctx.onSaveError(error);
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
    const checkedRadio = els.speedSourceRadios.find((radio) => radio.checked);
    const src: SpeedSourceKind = speedSourceDraftDirty && checkedRadio && isSpeedSourceKind(checkedRadio.value)
      ? checkedRadio.value
      : settings.speedSource;
    if (src === "obd2" && !settings.obdDeviceMac) {
      ctx.showError(t("settings.speed.obd_missing_device_error"));
      return;
    }
    const payload: SpeedSourceRequest = {
      speed_source: src,
      manual_speed_kph: parseManualSpeedKph(Number(els.manualSpeedInput?.value)),
    };
    applyStaleTimeoutFromInput(payload);
    void syncSpeedSourceToServer(payload);
  }

  function bindHandlers(): void {
    els.speedSourceRadios.forEach((radio) => {
      radio.addEventListener("change", () => {
        speedSourceDraftDirty = true;
        syncSpeedSourceSelectionUi();
      });
    });
    els.saveSpeedSourceBtn?.addEventListener("click", saveSpeedSourceFromInputs);
    els.scanObdDevicesBtn?.addEventListener("click", () => {
      void scanObdDevices();
    });
    els.settingsTabs.forEach((tab) => {
      tab.addEventListener("click", scheduleObdBackgroundRescanSync);
      tab.addEventListener("keydown", (event) => {
        if (TAB_NAVIGATION_KEYS.has(event.key)) {
          scheduleObdBackgroundRescanSync();
        }
      });
    });
    els.menuButtons.forEach((button) => {
      button.addEventListener("click", scheduleObdBackgroundRescanSync);
      button.addEventListener("keydown", (event) => {
        if (TAB_NAVIGATION_KEYS.has(event.key)) {
          scheduleObdBackgroundRescanSync();
        }
      });
    });
    els.obdDeviceList?.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const button = target.closest<HTMLButtonElement>("[data-obd-pair-mac]");
      const macAddress = button?.dataset.obdPairMac;
      if (!macAddress) {
        return;
      }
      void pairObdDevice(macAddress);
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

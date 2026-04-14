import type { ObdDevicePayload } from "../../transport/http_models";
import {
  deriveDisplayedSpeedSourceMode,
  isManualLikeSpeedSource,
  resolveEffectiveSpeedSource,
  type DisplayedSpeedSourceMode,
  type SpeedSourceStateSource,
} from "../speed_source_state";
import { createElementNode, renderChildren } from "./dom_render";
import type { SettingsSpeedSourcePanelDom } from "./speed_source_panel";
import {
  setSettingsFeedback,
  type SettingsFeedbackMessage,
} from "./settings_feedback";
import { setChoiceCardState } from "../style_state";

export interface SettingsSpeedSourceSettingsSnapshot
  extends SpeedSourceStateSource {
  gpsEffectiveSpeedKph: number | null;
  obdDeviceMac: string | null;
  obdDeviceName: string | null;
}

export interface SettingsSpeedSourceRenderState {
  diagnosticsOpen: boolean;
  draftDirty: boolean;
  manualSpeedFeedback: SettingsFeedbackMessage | null;
  manualSpeedInputValue: string;
  obdScanStatusMessage: string | null;
  obdSelectionError: boolean;
  pairInFlightMac: string | null;
  saveFeedback: SettingsFeedbackMessage | null;
  scannedDevices: readonly ObdDevicePayload[];
  scanInFlight: boolean;
  selectedMode: DisplayedSpeedSourceMode;
  settings: SettingsSpeedSourceSettingsSnapshot;
  staleTimeoutFeedback: SettingsFeedbackMessage | null;
  staleTimeoutInputValue: string;
}

export interface SettingsSpeedSourcePresenterDeps {
  dom: Pick<
    SettingsSpeedSourcePanelDom,
    | "gpsFallbackPanel"
    | "manualSpeedConfig"
    | "manualSpeedFeedback"
    | "manualSpeedInput"
    | "obdConfiguredDevice"
    | "obdDeviceList"
    | "obdDeviceScanStatus"
    | "obdSpeedConfig"
    | "saveSpeedSourceBtn"
    | "scanObdDevicesBtn"
    | "speedSourceChoiceGps"
    | "speedSourceChoiceManual"
    | "speedSourceChoiceObd"
    | "speedSourceCurrentSource"
    | "speedSourceDiagnostics"
    | "speedSourceEffectiveSpeed"
    | "speedSourceRadios"
    | "speedSourceSaveFeedback"
    | "staleTimeoutFeedback"
    | "staleTimeoutInput"
  >;
  fmt: (value: number, digits?: number) => string;
  getSpeedUnit: () => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface SettingsSpeedSourcePresenter {
  focusManualSpeedInput(): void;
  focusScanObdDevices(): void;
  focusStaleTimeoutInput(): void;
  isObdConfigVisible(): boolean;
  render(state: SettingsSpeedSourceRenderState): void;
}

function selectedSpeedUnitLabel(
  deps: Pick<SettingsSpeedSourcePresenterDeps, "getSpeedUnit" | "t">,
): string {
  return deps.getSpeedUnit() === "mps"
    ? deps.t("speed.unit.mps")
    : deps.t("speed.unit.kmh");
}

function speedKphInSelectedUnit(
  speedKmh: number | null,
  deps: Pick<SettingsSpeedSourcePresenterDeps, "getSpeedUnit">,
): number | null {
  if (speedKmh === null || !Number.isFinite(speedKmh)) {
    return null;
  }
  return deps.getSpeedUnit() === "mps" ? speedKmh / 3.6 : speedKmh;
}

function formatSpeedValue(
  speedKmh: number | null,
  deps: Pick<SettingsSpeedSourcePresenterDeps, "fmt" | "getSpeedUnit" | "t">,
): string {
  const speed = speedKphInSelectedUnit(speedKmh, deps);
  return speed != null
    ? `${deps.fmt(speed, 1)} ${selectedSpeedUnitLabel(deps)}`
    : "--";
}

function formatConfiguredObdDevice(
  settings: Pick<
    SettingsSpeedSourceSettingsSnapshot,
    "obdDeviceMac" | "obdDeviceName"
  >,
  t: SettingsSpeedSourcePresenterDeps["t"],
): string {
  if (settings.obdDeviceName && settings.obdDeviceMac) {
    return `${settings.obdDeviceName} (${settings.obdDeviceMac})`;
  }
  return (
    settings.obdDeviceName ??
    settings.obdDeviceMac ??
    t("settings.speed.obd_not_configured")
  );
}

function activeSourceLabel(
  settings: SettingsSpeedSourceRenderState["settings"],
  t: SettingsSpeedSourcePresenterDeps["t"],
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

function activeEffectiveSpeedKph(
  settings: SettingsSpeedSourceRenderState["settings"],
): number | null {
  return isManualLikeSpeedSource(resolveEffectiveSpeedSource(settings))
    ? settings.manualSpeedKph
    : settings.gpsEffectiveSpeedKph;
}

function syncChoiceState(
  element: HTMLElement | null,
  t: SettingsSpeedSourcePresenterDeps["t"],
  {
    active,
    pending,
    error,
  }: { active: boolean; pending: boolean; error: boolean },
): void {
  setChoiceCardState(element, {
    selected: active,
    state: error ? "error" : pending ? "draft" : active ? "active" : null,
    badgeText: pending
      ? t("settings.speed.choice_pending")
      : active
        ? t("settings.speed.choice_active")
        : null,
  });
}

function applyInputFeedback(
  input: HTMLInputElement | null,
  feedback: HTMLElement | null,
  message: SettingsFeedbackMessage | null,
): void {
  if (!message) {
    input?.removeAttribute("aria-invalid");
    input?.removeAttribute("aria-describedby");
    setSettingsFeedback(feedback, null);
    return;
  }
  if (feedback?.id) {
    input?.setAttribute("aria-describedby", feedback.id);
  }
  input?.setAttribute("aria-invalid", "true");
  setSettingsFeedback(feedback, message);
}

function looksLikeMacAlias(rawValue: string | null | undefined): boolean {
  const value = rawValue?.trim();
  return value != null && /^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(value);
}

function hasHumanReadableDeviceName(device: ObdDevicePayload): boolean {
  const value = device.name?.trim();
  return Boolean(value) && !looksLikeMacAlias(value);
}

function obdDevicePrimaryLabel(device: ObdDevicePayload): string {
  return device.name?.trim() || device.mac_address;
}

function obdDeviceSecondaryLabel(device: ObdDevicePayload): string | null {
  return hasHumanReadableDeviceName(device) ? device.mac_address : null;
}

function createBadge(label: string, active = false): HTMLSpanElement {
  return createElementNode("span", {
    className: "speed-source-device__badge",
    data: {
      active: active ? "true" : null,
    },
    text: label,
  });
}

function createObdDeviceRow(
  device: ObdDevicePayload,
  state: SettingsSpeedSourceRenderState,
  t: SettingsSpeedSourcePresenterDeps["t"],
): HTMLDivElement {
  const badges = [];
  if (device.mac_address === state.settings.obdDeviceMac) {
    badges.push(createBadge(t("settings.speed.obd_configured_badge"), true));
  }
  if (device.paired) {
    badges.push(createBadge(t("settings.speed.obd_paired_badge")));
  }
  if (device.trusted) {
    badges.push(createBadge(t("settings.speed.obd_trusted_badge")));
  }
  if (device.connected) {
    badges.push(createBadge(t("settings.speed.obd_connected_badge"), true));
  }

  const actionLabel =
    state.pairInFlightMac === device.mac_address
      ? t("settings.speed.obd_pairing")
      : device.paired && device.trusted
        ? t("settings.speed.obd_use")
        : t("settings.speed.obd_pair_and_use");
  const secondaryLabel = obdDeviceSecondaryLabel(device);

  return createElementNode("div", {
    className: "speed-source-device",
    children: [
      createElementNode("div", {
        className: "speed-source-device__header",
        children: [
          createElementNode("div", {
            className: "speed-source-device__identity",
            children: [
              createElementNode("div", {
                className: "speed-source-device__name",
                text: obdDevicePrimaryLabel(device),
              }),
              secondaryLabel
                ? createElementNode("div", {
                    className: "speed-source-device__mac",
                    text: secondaryLabel,
                  })
                : null,
            ],
          }),
          createElementNode("div", {
            className: "speed-source-device__badges",
            children: badges,
          }),
        ],
      }),
      createElementNode("div", {
        className: "speed-source-device__actions",
        children: [
          createElementNode("button", {
            className: "btn btn--secondary",
            attrs: {
              disabled: state.scanInFlight || state.pairInFlightMac !== null,
              type: "button",
            },
            data: {
              obdPairMac: device.mac_address,
            },
            text: actionLabel,
          }),
        ],
      }),
    ],
  });
}

function renderObdDeviceList(
  container: HTMLElement | null,
  state: SettingsSpeedSourceRenderState,
  t: SettingsSpeedSourcePresenterDeps["t"],
): void {
  if (!container) {
    return;
  }
  if (state.scannedDevices.length === 0) {
    renderChildren(container);
    return;
  }
  renderChildren(
    container,
    state.scannedDevices.map((device) => createObdDeviceRow(device, state, t)),
  );
}

export function createSettingsSpeedSourcePresenter(
  deps: SettingsSpeedSourcePresenterDeps,
): SettingsSpeedSourcePresenter {
  const { dom, t } = deps;

  function render(state: SettingsSpeedSourceRenderState): void {
    const displayedMode = deriveDisplayedSpeedSourceMode(state.settings);
    const hasPendingSelection =
      state.draftDirty && state.selectedMode !== displayedMode;

    dom.speedSourceRadios.forEach((radio) => {
      radio.checked = radio.value === state.selectedMode;
    });

    if (dom.manualSpeedInput) {
      dom.manualSpeedInput.value = state.manualSpeedInputValue;
    }
    if (dom.staleTimeoutInput) {
      dom.staleTimeoutInput.value = state.staleTimeoutInputValue;
    }

    syncChoiceState(dom.speedSourceChoiceGps, t, {
      active: displayedMode === "gps",
      pending: hasPendingSelection && state.selectedMode === "gps",
      error: false,
    });
    syncChoiceState(dom.speedSourceChoiceObd, t, {
      active: displayedMode === "obd2",
      pending: hasPendingSelection && state.selectedMode === "obd2",
      error: state.obdSelectionError,
    });
    syncChoiceState(dom.speedSourceChoiceManual, t, {
      active: displayedMode === "manual",
      pending: hasPendingSelection && state.selectedMode === "manual",
      error: false,
    });

    if (dom.manualSpeedConfig) {
      dom.manualSpeedConfig.hidden = state.selectedMode !== "manual";
    }
    if (dom.obdSpeedConfig) {
      dom.obdSpeedConfig.hidden = state.selectedMode !== "obd2";
    }
    if (dom.gpsFallbackPanel) {
      dom.gpsFallbackPanel.hidden = state.selectedMode === "manual";
    }

    if (dom.speedSourceCurrentSource) {
      dom.speedSourceCurrentSource.textContent = activeSourceLabel(
        state.settings,
        t,
      );
    }
    if (dom.speedSourceEffectiveSpeed) {
      dom.speedSourceEffectiveSpeed.textContent = formatSpeedValue(
        activeEffectiveSpeedKph(state.settings),
        deps,
      );
    }
    if (dom.obdConfiguredDevice) {
      dom.obdConfiguredDevice.textContent = formatConfiguredObdDevice(
        state.settings,
        t,
      );
    }
    if (dom.scanObdDevicesBtn) {
      dom.scanObdDevicesBtn.disabled =
        state.scanInFlight || state.pairInFlightMac !== null;
    }
    if (dom.obdDeviceScanStatus) {
      dom.obdDeviceScanStatus.textContent =
        state.obdScanStatusMessage ?? t("settings.speed.obd_scan_idle");
    }
    renderObdDeviceList(dom.obdDeviceList, state, t);

    applyInputFeedback(
      dom.manualSpeedInput,
      dom.manualSpeedFeedback,
      state.manualSpeedFeedback,
    );
    applyInputFeedback(
      dom.staleTimeoutInput,
      dom.staleTimeoutFeedback,
      state.staleTimeoutFeedback,
    );
    setSettingsFeedback(dom.speedSourceSaveFeedback, state.saveFeedback);

    const obdRadio = dom.speedSourceRadios.find(
      (radio) => radio.value === "obd2",
    );
    if (state.obdSelectionError) {
      obdRadio?.setAttribute("aria-invalid", "true");
    } else {
      obdRadio?.removeAttribute("aria-invalid");
    }

    if (state.diagnosticsOpen) {
      dom.speedSourceDiagnostics?.setAttribute("open", "");
    }
  }

  function isObdConfigVisible(): boolean {
    if (!dom.obdSpeedConfig || dom.obdSpeedConfig.hidden) {
      return false;
    }
    const activePanel = dom.obdSpeedConfig.closest<HTMLElement>(
      ".settings-tab-panel",
    );
    if (!activePanel || activePanel.hidden) {
      return false;
    }
    const activeView = activePanel.closest<HTMLElement>(".view");
    return activeView == null || !activeView.hidden;
  }

  return {
    focusManualSpeedInput(): void {
      dom.manualSpeedInput?.focus();
    },
    focusScanObdDevices(): void {
      dom.scanObdDevicesBtn?.focus();
    },
    focusStaleTimeoutInput(): void {
      dom.staleTimeoutInput?.focus();
    },
    isObdConfigVisible,
    render,
  };
}

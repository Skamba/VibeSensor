import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../transport/http_models";
import type { UiUpdateDom } from "../dom/update_dom";
import {
  formatUsbInternetSummary,
  renderInternetStatusPanel,
} from "./internet_status_view";
import {
  renderMaintenanceReadinessPanel,
  type MaintenanceReadinessPanelModel,
} from "./maintenance_readiness_view";
import {
  buildUpdateStatusPanelViewModel,
  getUpdateFailureSummary,
} from "./update_status_view_models";
import { renderUpdateStatusPanel } from "./update_status_view";

export interface UpdateFeatureRenderState {
  internetStatus: UsbInternetStatusPayload;
  healthStatus: HealthStatusPayload | null;
  updateStatus: UpdateStatusPayload | null;
  updateState: UpdateStatusPayload["state"];
  updateTransport: UpdateStartRequestPayload["transport"];
}

export interface UpdateFeatureStartIntent {
  canStart: boolean;
  password: string;
  ssid: string;
  transport: UpdateStartRequestPayload["transport"];
  usbAvailable: boolean;
}

interface UpdateFeatureActionSummary {
  canStart: boolean;
  panelModel: MaintenanceReadinessPanelModel;
  startLabel: string;
  transport: UpdateStartRequestPayload["transport"];
}

export interface UpdateFeaturePresenterDeps {
  dom: UiUpdateDom;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
}

export interface UpdateFeaturePresenter {
  render(state: UpdateFeatureRenderState): void;
  readStartIntent(state: UpdateFeatureRenderState): UpdateFeatureStartIntent;
  togglePassword(): void;
  focusSsidInput(): void;
  clearPassword(): void;
}

export function createUpdateFeaturePresenter(
  ctx: UpdateFeaturePresenterDeps,
): UpdateFeaturePresenter {
  const { dom: els, t, escapeHtml } = ctx;

  let passwordVisible = false;
  let lastActionSummary: UpdateFeatureActionSummary | null = null;

  function selectedTransport(
    state: UpdateFeatureRenderState,
  ): UpdateStartRequestPayload["transport"] {
    if (state.updateState === "running") {
      return state.updateTransport;
    }
    if (state.internetStatus.usable && els.updateTransportUsbRadio?.checked) {
      return "usb_internet";
    }
    return "wifi";
  }

  function hasBlockingHealthIssue(
    state: UpdateFeatureRenderState,
  ): boolean {
    const health = state.healthStatus;
    if (!health) {
      return false;
    }
    return (
      health.status === "degraded"
      || health.persistence.write_error != null
      || health.startup_error != null
      || health.db_corruption_detected === true
    );
  }

  function buildActionSummary(
    state: UpdateFeatureRenderState,
  ): UpdateFeatureActionSummary {
    const transport = selectedTransport(state);
    const usingUsb = transport === "usb_internet";
    const isRunning = state.updateState === "running";
    const ssid = els.updateSsidInput?.value.trim() ?? "";
    const usbInterface = state.internetStatus.interface_name;
    const readinessItems = [
      {
        label: t("settings.update.readiness.item.source"),
        detail: usingUsb
          ? t("settings.update.readiness.item.source_usb")
          : t("settings.update.readiness.item.source_wifi"),
        state: "ready" as const,
      },
      usingUsb
        ? {
            label: t("settings.update.readiness.item.connection"),
            detail: state.internetStatus.usable
              ? t("settings.update.readiness.item.connection_usb_ready", {
                  interface: usbInterface || t("settings.update.transport.usb_title"),
                })
              : t("settings.update.readiness.item.connection_usb_blocked"),
            state: state.internetStatus.usable ? ("ready" as const) : ("blocked" as const),
          }
        : {
            label: t("settings.update.readiness.item.connection"),
            detail: ssid
              ? t("settings.update.readiness.item.connection_wifi_ready")
              : t("settings.update.readiness.item.connection_wifi_blocked"),
            state: ssid ? ("ready" as const) : ("blocked" as const),
          },
    ];
    if (hasBlockingHealthIssue(state)) {
      readinessItems.push({
        label: t("settings.update.readiness.item.health"),
        detail: t("settings.update.readiness.item.health_blocked"),
        state: "blocked",
      });
    }
    const hasBlockedItem = readinessItems.some((item) => item.state === "blocked");
    const failure = state.updateStatus ? getUpdateFailureSummary(state.updateStatus, t) : null;
    const isRecoveryState = failure !== null;
    const stateLabel = isRecoveryState
      ? hasBlockedItem
        ? t("maintenance.readiness.blocked")
        : t("settings.update.state.failed")
      : isRunning
        ? t("maintenance.readiness.running")
        : hasBlockedItem
          ? t("maintenance.readiness.blocked")
          : t("maintenance.readiness.ready");
    const items = failure
      ? [
          {
            label: t("settings.update.recovery.item.failed_step"),
            detail: failure.phaseLabel,
            state: "attention" as const,
          },
          {
            label: t("settings.update.recovery.item.captured_detail"),
            detail: failure.message
              ? failure.detail
                ? `${failure.message} — ${failure.detail}`
                : failure.message
              : failure.detail || failure.phaseLabel,
            state: "attention" as const,
          },
          {
            label: t("settings.update.recovery.item.next_step"),
            detail: hasBlockedItem
              ? t("settings.update.recovery.item.next_step_blocked")
              : `${failure.recoveryTitle} — ${failure.recoveryDetail}`,
            state: hasBlockedItem ? ("blocked" as const) : ("attention" as const),
          },
        ]
      : readinessItems;
    return {
      canStart: !isRunning && !hasBlockedItem,
      startLabel: t(isRecoveryState ? "settings.update.retry" : "settings.update.start"),
      transport,
      panelModel: {
        title: t(
          isRecoveryState
            ? "settings.update.recovery.title"
            : "settings.update.readiness.title",
        ),
        summary: t(
          isRecoveryState
            ? hasBlockedItem
              ? "settings.update.recovery.summary_blocked"
              : "settings.update.recovery.summary_retry"
            : isRunning
              ? "settings.update.readiness.summary_running"
              : hasBlockedItem
                ? "settings.update.readiness.summary_blocked"
                : "settings.update.readiness.summary_ready",
        ),
        stateLabel,
        stateVariant: isRecoveryState ? "bad" : isRunning ? "warn" : hasBlockedItem ? "bad" : "ok",
        items,
      },
    };
  }

  function syncTransportUi(state: UpdateFeatureRenderState): void {
    const usbAvailable = state.internetStatus.usable;
    const controlsLocked = state.updateState === "running";
    const usingUsb = selectedTransport(state) === "usb_internet";
    if (els.updateTransportOptions) {
      els.updateTransportOptions.hidden = false;
    }
    if (els.updateUsbTransportSummary) {
      els.updateUsbTransportSummary.textContent = usbAvailable
        ? formatUsbInternetSummary(state.internetStatus, t)
        : t("settings.update.transport.usb_summary_unavailable");
    }
    if (!usbAvailable && !controlsLocked) {
      if (els.updateTransportWifiRadio) {
        els.updateTransportWifiRadio.checked = true;
      }
      if (els.updateTransportUsbRadio) {
        els.updateTransportUsbRadio.checked = false;
      }
    }
    if (els.updateTransportWifiRadio) {
      els.updateTransportWifiRadio.disabled = controlsLocked;
    }
    if (els.updateTransportUsbRadio) {
      els.updateTransportUsbRadio.disabled = controlsLocked || !usbAvailable;
    }
    if (controlsLocked) {
      if (els.updateTransportWifiRadio) {
        els.updateTransportWifiRadio.checked = !usingUsb;
      }
      if (els.updateTransportUsbRadio) {
        els.updateTransportUsbRadio.checked = usingUsb;
      }
    }
    els.updateTransportChoiceWifi?.classList.toggle("speed-source-choice--selected", !usingUsb);
    els.updateTransportChoiceUsb?.classList.toggle("speed-source-choice--selected", usingUsb);
    els.updateTransportChoiceUsb?.classList.toggle(
      "speed-source-choice--disabled",
      !usbAvailable && !controlsLocked,
    );
    if (els.updateWifiFields) {
      els.updateWifiFields.hidden = usingUsb;
    }
    if (els.updateTransportNote) {
      els.updateTransportNote.textContent = t(
        usingUsb
          ? "settings.update.preflight_note_usb"
          : "settings.update.preflight_note_wifi",
      );
    }
    if (els.updateDetailsCaption) {
      els.updateDetailsCaption.textContent = t(
        usingUsb
          ? "settings.update.details_caption_usb"
          : "settings.update.details_caption_wifi",
      );
    }
  }

  function syncControls(
    state: UpdateFeatureRenderState,
    actionSummary: UpdateFeatureActionSummary,
  ): void {
    const isRunning = state.updateState === "running";
    els.updateStartBtn.textContent = actionSummary.startLabel;
    els.updateStartBtn.hidden = isRunning;
    els.updateStartBtn.disabled = isRunning || !actionSummary.canStart;
    if (els.updateCancelBtn) {
      els.updateCancelBtn.hidden = !isRunning;
      els.updateCancelBtn.disabled = !isRunning;
    }
    if (els.updateSsidInput) {
      els.updateSsidInput.disabled = isRunning;
    }
    if (els.updatePasswordInput) {
      els.updatePasswordInput.disabled = isRunning;
    }
    if (els.updateTogglePasswordBtn) {
      els.updateTogglePasswordBtn.disabled = isRunning;
    }
  }

  function renderPanels(
    state: UpdateFeatureRenderState,
    actionSummary: UpdateFeatureActionSummary,
  ): void {
    if (els.updateReadinessSummary) {
      els.updateReadinessSummary.innerHTML = renderMaintenanceReadinessPanel(
        actionSummary.panelModel,
        escapeHtml,
      );
    }
    if (
      els.updateStatusPanel
      && state.updateStatus
      && state.healthStatus
    ) {
      renderUpdateStatusPanel(
        els.updateStatusPanel,
        buildUpdateStatusPanelViewModel(state.updateStatus, state.healthStatus, {
          t,
          selectedTransport: actionSummary.transport,
        }),
      );
    }
    if (
      els.internetStatusPanel
      && state.updateStatus
      && state.healthStatus
    ) {
      renderInternetStatusPanel(els.internetStatusPanel, state.internetStatus, {
        t,
      });
    }
  }

  function render(state: UpdateFeatureRenderState): void {
    syncTransportUi(state);
    const actionSummary = buildActionSummary(state);
    lastActionSummary = actionSummary;
    syncControls(state, actionSummary);
    renderPanels(state, actionSummary);
  }

  function readStartIntent(
    state: UpdateFeatureRenderState,
  ): UpdateFeatureStartIntent {
    const actionSummary = lastActionSummary ?? buildActionSummary(state);
    return {
      canStart: actionSummary.canStart,
      password: els.updatePasswordInput?.value ?? "",
      ssid: els.updateSsidInput?.value.trim() ?? "",
      transport: actionSummary.transport,
      usbAvailable: state.internetStatus.usable,
    };
  }

  function togglePassword(): void {
    passwordVisible = !passwordVisible;
    if (els.updatePasswordInput) {
      els.updatePasswordInput.type = passwordVisible ? "text" : "password";
    }
    if (els.updateTogglePasswordBtn) {
      const span = els.updateTogglePasswordBtn.querySelector("span");
      if (span) {
        span.textContent = t(
          passwordVisible
            ? "settings.update.hide_password"
            : "settings.update.show_password",
        );
      }
    }
  }

  return {
    render,
    readStartIntent,
    togglePassword,
    focusSsidInput() {
      els.updateSsidInput?.focus();
    },
    clearPassword() {
      if (els.updatePasswordInput) {
        els.updatePasswordInput.value = "";
      }
    },
  };
}

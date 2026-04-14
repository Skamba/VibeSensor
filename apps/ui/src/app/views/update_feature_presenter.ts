import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../transport/http_models";
import type { InternetPanelDom } from "./internet_panel";
import type { UpdatePanelDom } from "./update_panel";
import {
  formatUsbInternetSummary,
  renderInternetStatusPanel,
} from "./internet_status_view";
import { setChoiceCardState } from "../style_state";
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
  dom: UpdatePanelDom;
  internetDom: InternetPanelDom;
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
  const { dom: updateEls, internetDom, t, escapeHtml } = ctx;

  let passwordVisible = false;
  let lastActionSummary: UpdateFeatureActionSummary | null = null;

  function selectedTransport(
    state: UpdateFeatureRenderState,
  ): UpdateStartRequestPayload["transport"] {
    if (state.updateState === "running") {
      return state.updateTransport;
    }
    if (
      state.internetStatus.usable &&
      internetDom.updateTransportUsbRadio?.checked
    ) {
      return "usb_internet";
    }
    return "wifi";
  }

  function hasBlockingHealthIssue(state: UpdateFeatureRenderState): boolean {
    const health = state.healthStatus;
    if (!health) {
      return false;
    }
    return (
      health.status === "degraded" ||
      health.persistence.write_error != null ||
      health.startup_error != null ||
      health.db_corruption_detected === true
    );
  }

  function buildActionSummary(
    state: UpdateFeatureRenderState,
  ): UpdateFeatureActionSummary {
    const transport = selectedTransport(state);
    const usingUsb = transport === "usb_internet";
    const isRunning = state.updateState === "running";
    const ssid = internetDom.updateSsidInput?.value.trim() ?? "";
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
                  interface:
                    usbInterface || t("settings.update.transport.usb_title"),
                })
              : t("settings.update.readiness.item.connection_usb_blocked"),
            state: state.internetStatus.usable
              ? ("ready" as const)
              : ("blocked" as const),
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
    const hasBlockedItem = readinessItems.some(
      (item) => item.state === "blocked",
    );
    const failure = state.updateStatus
      ? getUpdateFailureSummary(state.updateStatus, t)
      : null;
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
            state: hasBlockedItem
              ? ("blocked" as const)
              : ("attention" as const),
          },
        ]
      : readinessItems;
    return {
      canStart: !isRunning && !hasBlockedItem,
      startLabel: t(
        isRecoveryState ? "settings.update.retry" : "settings.update.start",
      ),
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
        stateVariant: isRecoveryState
          ? "bad"
          : isRunning
            ? "warn"
            : hasBlockedItem
              ? "bad"
              : "ok",
        items,
      },
    };
  }

  function syncTransportUi(state: UpdateFeatureRenderState): void {
    const usbAvailable = state.internetStatus.usable;
    const controlsLocked = state.updateState === "running";
    const usingUsb = selectedTransport(state) === "usb_internet";
    if (internetDom.updateTransportOptions) {
      internetDom.updateTransportOptions.hidden = false;
    }
    if (internetDom.updateUsbTransportSummary) {
      internetDom.updateUsbTransportSummary.textContent = usbAvailable
        ? formatUsbInternetSummary(state.internetStatus, t)
        : t("settings.update.transport.usb_summary_unavailable");
    }
    if (!usbAvailable && !controlsLocked) {
      if (internetDom.updateTransportWifiRadio) {
        internetDom.updateTransportWifiRadio.checked = true;
      }
      if (internetDom.updateTransportUsbRadio) {
        internetDom.updateTransportUsbRadio.checked = false;
      }
    }
    if (internetDom.updateTransportWifiRadio) {
      internetDom.updateTransportWifiRadio.disabled = controlsLocked;
    }
    if (internetDom.updateTransportUsbRadio) {
      internetDom.updateTransportUsbRadio.disabled =
        controlsLocked || !usbAvailable;
    }
    if (controlsLocked) {
      if (internetDom.updateTransportWifiRadio) {
        internetDom.updateTransportWifiRadio.checked = !usingUsb;
      }
      if (internetDom.updateTransportUsbRadio) {
        internetDom.updateTransportUsbRadio.checked = usingUsb;
      }
    }
    setChoiceCardState(internetDom.updateTransportChoiceWifi, {
      selected: !usingUsb,
    });
    setChoiceCardState(internetDom.updateTransportChoiceUsb, {
      selected: usingUsb,
      disabled: !usbAvailable && !controlsLocked,
    });
    if (internetDom.updateWifiFields) {
      internetDom.updateWifiFields.hidden = usingUsb;
    }
    if (internetDom.updateTransportNote) {
      internetDom.updateTransportNote.textContent = t(
        usingUsb
          ? "settings.update.preflight_note_usb"
          : "settings.update.preflight_note_wifi",
      );
    }
    if (internetDom.updateDetailsCaption) {
      internetDom.updateDetailsCaption.textContent = t(
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
    updateEls.updateStartBtn.textContent = actionSummary.startLabel;
    updateEls.updateStartBtn.hidden = isRunning;
    updateEls.updateStartBtn.disabled = isRunning || !actionSummary.canStart;
    updateEls.updateCancelBtn.hidden = !isRunning;
    updateEls.updateCancelBtn.disabled = !isRunning;
    if (internetDom.updateSsidInput) {
      internetDom.updateSsidInput.disabled = isRunning;
    }
    if (internetDom.updatePasswordInput) {
      internetDom.updatePasswordInput.disabled = isRunning;
    }
    if (internetDom.updateTogglePasswordBtn) {
      internetDom.updateTogglePasswordBtn.disabled = isRunning;
    }
  }

  function renderPanels(
    state: UpdateFeatureRenderState,
    actionSummary: UpdateFeatureActionSummary,
  ): void {
    if (internetDom.updateReadinessSummary) {
      internetDom.updateReadinessSummary.innerHTML =
        renderMaintenanceReadinessPanel(actionSummary.panelModel, escapeHtml);
    }
    if (state.updateStatus && state.healthStatus) {
      renderUpdateStatusPanel(
        updateEls.updateStatusPanel,
        buildUpdateStatusPanelViewModel(
          state.updateStatus,
          state.healthStatus,
          {
            t,
            selectedTransport: actionSummary.transport,
          },
        ),
      );
    }
    if (
      internetDom.internetStatusPanel &&
      state.updateStatus &&
      state.healthStatus
    ) {
      renderInternetStatusPanel(
        internetDom.internetStatusPanel,
        state.internetStatus,
        {
          t,
        },
      );
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
      password: internetDom.updatePasswordInput?.value ?? "",
      ssid: internetDom.updateSsidInput?.value.trim() ?? "",
      transport: actionSummary.transport,
      usbAvailable: state.internetStatus.usable,
    };
  }

  function togglePassword(): void {
    passwordVisible = !passwordVisible;
    if (internetDom.updatePasswordInput) {
      internetDom.updatePasswordInput.type = passwordVisible
        ? "text"
        : "password";
    }
    if (internetDom.updateTogglePasswordBtn) {
      const span = internetDom.updateTogglePasswordBtn.querySelector("span");
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
      internetDom.updateSsidInput?.focus();
    },
    clearPassword() {
      if (internetDom.updatePasswordInput) {
        internetDom.updatePasswordInput.value = "";
      }
    },
  };
}

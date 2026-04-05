import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../transport/http_models";
import {
  cancelUpdate,
  getHealthStatus,
  getUpdateInternetStatus,
  getUpdateStatus,
  startUpdate,
} from "../../api/settings";
import {
  UPDATE_POLL_INTERVAL_IDLE_MS,
  UPDATE_POLL_INTERVAL_RUNNING_MS,
} from "../../config";
import type { UiUpdateDom } from "../dom/update_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import { createPollingController } from "./polling_controller";
import {
  formatUsbInternetSummary,
  renderInternetStatusPanel,
} from "../views/internet_status_view";
import { renderMaintenanceReadinessPanel } from "../views/maintenance_readiness_view";
import {
  getUpdateFailureSummary,
  renderUpdateStatusPanel,
} from "../views/update_status_view";

export interface UpdateFeatureDeps extends FeatureDepsBase {
  dom: UiUpdateDom;
}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

interface UpdateActionSummary {
  canStart: boolean;
  detailsCaption: string;
  html: string;
  startLabel: string;
}

function fallbackInternetStatus(
  t: (key: string, vars?: Record<string, unknown>) => string,
): UsbInternetStatusPayload {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: t("settings.internet.load_failed"),
  };
}

function normalizeInternetStatus(
  payload: unknown,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UsbInternetStatusPayload {
  if (!payload || typeof payload !== "object") {
    return fallbackInternetStatus(t);
  }
  const record = payload as Record<string, unknown>;
  return {
    detected: record.detected === true,
    usable: record.usable === true,
    interface_name: typeof record.interface_name === "string" ? record.interface_name : null,
    connection_name: typeof record.connection_name === "string" ? record.connection_name : null,
    driver: typeof record.driver === "string" ? record.driver : null,
    ipv4_addresses: Array.isArray(record.ipv4_addresses)
      ? record.ipv4_addresses.filter((value): value is string => typeof value === "string")
      : [],
    gateway: typeof record.gateway === "string" ? record.gateway : null,
    has_default_route: record.has_default_route === true,
    diagnostic: typeof record.diagnostic === "string"
      ? record.diagnostic
      : t("settings.internet.load_failed"),
  };
}

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { dom: els, t, escapeHtml } = ctx;

  let passwordVisible = false;
  let latestInternetStatus: UsbInternetStatusPayload = fallbackInternetStatus(t);
  let latestHealthStatus: HealthStatusPayload | null = null;
  let latestUpdateStatus: UpdateStatusPayload | null = null;
  let latestUpdateState: UpdateStatusPayload["state"] = "idle";
  let latestUpdateTransport: UpdateStartRequestPayload["transport"] = "wifi";

  function safeUpdateTransport(
    transport: string | null | undefined,
  ): UpdateStartRequestPayload["transport"] {
    return transport === "usb_internet" ? "usb_internet" : "wifi";
  }

  function selectedTransport(): UpdateStartRequestPayload["transport"] {
    if (latestUpdateState === "running") {
      return latestUpdateTransport;
    }
    if (latestInternetStatus.usable && els.updateTransportUsbRadio?.checked) {
      return "usb_internet";
    }
    return "wifi";
  }

  function hasBlockingHealthIssue(): boolean {
    const health = latestHealthStatus;
    if (!health) return false;
    return (
      health.status === "degraded" ||
      health.persistence.write_error != null ||
      health.startup_error != null ||
      health.db_corruption_detected === true
    );
  }

  function buildUpdateActionSummary(): UpdateActionSummary {
    const transport = selectedTransport();
    const usingUsb = transport === "usb_internet";
    const isRunning = latestUpdateState === "running";
    const ssid = els.updateSsidInput?.value.trim() ?? "";
    const usbInterface = latestInternetStatus.interface_name;
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
            detail: latestInternetStatus.usable
              ? t("settings.update.readiness.item.connection_usb_ready", {
                  interface: usbInterface || t("settings.update.transport.usb_title"),
                })
              : t("settings.update.readiness.item.connection_usb_blocked"),
            state: latestInternetStatus.usable ? ("ready" as const) : ("blocked" as const),
          }
        : {
            label: t("settings.update.readiness.item.connection"),
            detail: ssid
              ? t("settings.update.readiness.item.connection_wifi_ready")
              : t("settings.update.readiness.item.connection_wifi_blocked"),
            state: ssid ? ("ready" as const) : ("blocked" as const),
          },
    ];
    if (hasBlockingHealthIssue()) {
      readinessItems.push({
        label: t("settings.update.readiness.item.health"),
        detail: t("settings.update.readiness.item.health_blocked"),
        state: "blocked",
      });
    }
    const hasBlockedItem = readinessItems.some((item) => item.state === "blocked");
    const failure = latestUpdateStatus ? getUpdateFailureSummary(latestUpdateStatus, t) : null;
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
      detailsCaption: t(
        usingUsb
          ? "settings.update.details_caption_usb"
          : "settings.update.details_caption_wifi",
      ),
      startLabel: t(isRecoveryState ? "settings.update.retry" : "settings.update.start"),
      html: renderMaintenanceReadinessPanel(
        {
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
        escapeHtml,
      ),
    };
  }

  function syncUpdateControls(readiness: UpdateActionSummary): void {
    const isRunning = latestUpdateState === "running";
    if (els.updateStartBtn) {
      els.updateStartBtn.textContent = readiness.startLabel;
      els.updateStartBtn.hidden = isRunning;
      els.updateStartBtn.disabled = isRunning || !readiness.canStart;
    }
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

  function syncTransportUi(): void {
    const usbAvailable = latestInternetStatus.usable;
    const controlsLocked = latestUpdateState === "running";
    const usingUsb = selectedTransport() === "usb_internet";
    if (els.updateTransportOptions) {
      els.updateTransportOptions.hidden = false;
    }
    if (els.updateUsbTransportSummary) {
      els.updateUsbTransportSummary.textContent = usbAvailable
        ? formatUsbInternetSummary(latestInternetStatus, t)
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

  function syncUpdateReadinessUi(): UpdateActionSummary {
    const readiness = buildUpdateActionSummary();
    if (els.updateReadinessSummary) {
      els.updateReadinessSummary.innerHTML = readiness.html;
    }
    return readiness;
  }

  function renderStatus(
    status: UpdateStatusPayload,
    health: HealthStatusPayload,
    internet: UsbInternetStatusPayload,
  ): void {
    latestUpdateStatus = status;
    latestInternetStatus = internet;
    latestHealthStatus = health;
    latestUpdateState = status.state;
    latestUpdateTransport = safeUpdateTransport(status.transport);
    const panel = els.updateStatusPanel;
    syncTransportUi();
    syncUpdateControls(syncUpdateReadinessUi());
    if (panel) {
      renderUpdateStatusPanel(panel, status, health, {
        t,
        escapeHtml,
        selectedTransport: selectedTransport(),
      });
    }
    if (els.internetStatusPanel) {
      renderInternetStatusPanel(els.internetStatusPanel, internet, {
        t,
      });
    }
  }

  const polling = createPollingController({
    poll: async () => {
      const [status, health, internet] = await Promise.all([
        getUpdateStatus(),
        getHealthStatus(),
        getUpdateInternetStatus()
          .then((payload) => normalizeInternetStatus(payload, t))
          .catch(() => fallbackInternetStatus(t)),
      ]);
      renderStatus(status, health, internet);
      return status.state === "running"
        ? UPDATE_POLL_INTERVAL_RUNNING_MS
        : UPDATE_POLL_INTERVAL_IDLE_MS;
    },
    onErrorDelayMs: UPDATE_POLL_INTERVAL_RUNNING_MS,
  });

  async function handleStart(): Promise<void> {
    const transport = selectedTransport();
    const readiness = syncUpdateReadinessUi();
    syncUpdateControls(readiness);
    if (!readiness.canStart) {
      if (transport === "wifi" && !(els.updateSsidInput?.value?.trim() ?? "")) {
        els.updateSsidInput?.focus();
      }
      return;
    }
    let payload: UpdateStartRequestPayload;
    if (transport === "wifi") {
      const ssid = els.updateSsidInput?.value?.trim() ?? "";
      const password = els.updatePasswordInput?.value ?? "";
      if (!ssid) {
        els.updateSsidInput?.focus();
        return;
      }
      payload = { transport, ssid, password };
    } else {
      if (!latestInternetStatus.usable) {
        ctx.showError(t("settings.update.usb_unavailable"));
        return;
      }
      payload = { transport, password: "" };
    }

    try {
      await startUpdate(payload);
      if (els.updatePasswordInput) {
        els.updatePasswordInput.value = "";
      }
      polling.restart();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409")) {
        ctx.showError(t("settings.update.already_running"));
      } else {
        ctx.showError(`${t("settings.update.start_failed")}\n${msg}`);
      }
    }
  }

  async function handleCancel(): Promise<void> {
    try {
      await cancelUpdate();
      polling.restart();
    } catch {
      /* ignore */
    }
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

  function bindUpdateHandlers(): void {
    els.updateStartBtn?.addEventListener("click", () => void handleStart());
    els.updateCancelBtn?.addEventListener("click", () => void handleCancel());
    els.updateTogglePasswordBtn?.addEventListener("click", togglePassword);
    els.updateTransportWifiRadio?.addEventListener("change", () => {
      syncTransportUi();
      syncUpdateControls(syncUpdateReadinessUi());
    });
    els.updateTransportUsbRadio?.addEventListener("change", () => {
      syncTransportUi();
      syncUpdateControls(syncUpdateReadinessUi());
    });
    els.updateSsidInput?.addEventListener("input", () => {
      syncUpdateControls(syncUpdateReadinessUi());
    });
    syncTransportUi();
    syncUpdateControls(syncUpdateReadinessUi());
  }

  function startPolling(): void {
    polling.start();
  }

  function stopPolling(): void {
    polling.stop();
  }

  return {
    bindUpdateHandlers,
    startPolling,
    stopPolling,
  };
}

import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../api/types";
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
import type { FeatureDepsBase } from "../feature_deps_base";
import { createPollingController } from "./polling_controller";
import {
  formatUsbInternetSummary,
  renderInternetStatusPanel,
} from "../views/internet_status_view";
import {
  renderUpdateStatusPanel,
  syncUpdateControls,
} from "../views/update_status_view";

export interface UpdateFeatureDeps extends FeatureDepsBase {}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
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
  const { els, t, escapeHtml } = ctx;

  let passwordVisible = false;
  let latestInternetStatus: UsbInternetStatusPayload = fallbackInternetStatus(t);

  function selectedTransport(): UpdateStartRequestPayload["transport"] {
    if (latestInternetStatus.usable && els.updateTransportUsbRadio?.checked) {
      return "usb_internet";
    }
    return "wifi";
  }

  function syncTransportUi(): void {
    const usbAvailable = latestInternetStatus.usable;
    if (els.updateTransportOptions) {
      els.updateTransportOptions.hidden = !usbAvailable;
    }
    if (els.updateUsbTransportOption) {
      els.updateUsbTransportOption.hidden = !usbAvailable;
    }
    if (els.updateUsbTransportSummary) {
      els.updateUsbTransportSummary.textContent = formatUsbInternetSummary(latestInternetStatus, t);
    }
    if (!usbAvailable) {
      if (els.updateTransportWifiRadio) {
        els.updateTransportWifiRadio.checked = true;
      }
      if (els.updateTransportUsbRadio) {
        els.updateTransportUsbRadio.checked = false;
      }
    }
    const usingUsb = usbAvailable && els.updateTransportUsbRadio?.checked === true;
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
  }

  function renderStatus(
    status: UpdateStatusPayload,
    health: HealthStatusPayload,
    internet: UsbInternetStatusPayload,
  ): void {
    latestInternetStatus = internet;
    const panel = els.updateStatusPanel;
    syncUpdateControls(els, status);
    syncTransportUi();
    if (panel) {
      renderUpdateStatusPanel(panel, status, health, { t, escapeHtml });
    }
    if (els.internetStatusPanel) {
      renderInternetStatusPanel(els.internetStatusPanel, internet, {
        t,
        escapeHtml,
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
      payload = { transport };
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
    els.updateTransportWifiRadio?.addEventListener("change", syncTransportUi);
    els.updateTransportUsbRadio?.addEventListener("change", syncTransportUi);
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

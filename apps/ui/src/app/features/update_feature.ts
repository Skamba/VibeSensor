import type { HealthStatusPayload, UpdateStatusPayload } from "../../api/types";
import { getHealthStatus, getUpdateStatus, startUpdate, cancelUpdate } from "../../api/settings";
import {
  UPDATE_POLL_INTERVAL_IDLE_MS,
  UPDATE_POLL_INTERVAL_RUNNING_MS,
} from "../../config";
import type { FeatureDepsBase } from "../feature_deps_base";
import { createPollingController } from "./polling_controller";
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

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { els, t, escapeHtml } = ctx;

  let passwordVisible = false;

  function renderStatus(status: UpdateStatusPayload, health: HealthStatusPayload): void {
    const panel = els.updateStatusPanel;
    if (!panel) return;
    syncUpdateControls(els, status);
    renderUpdateStatusPanel(panel, status, health, { t, escapeHtml });
  }

  const polling = createPollingController({
    poll: async () => {
      const [status, health] = await Promise.all([getUpdateStatus(), getHealthStatus()]);
      renderStatus(status, health);
      return status.state === "running"
        ? UPDATE_POLL_INTERVAL_RUNNING_MS
        : UPDATE_POLL_INTERVAL_IDLE_MS;
    },
    onErrorDelayMs: UPDATE_POLL_INTERVAL_RUNNING_MS,
  });

  async function handleStart(): Promise<void> {
    const ssid = els.updateSsidInput?.value?.trim() ?? "";
    const password = els.updatePasswordInput?.value ?? "";

    if (!ssid) {
      els.updateSsidInput?.focus();
      return;
    }

    try {
      await startUpdate(ssid, password);
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
        span.textContent = t(passwordVisible ? "settings.update.hide_password" : "settings.update.show_password");
      }
    }
  }

  function bindUpdateHandlers(): void {
    els.updateStartBtn?.addEventListener("click", () => void handleStart());
    els.updateCancelBtn?.addEventListener("click", () => void handleCancel());
    els.updateTogglePasswordBtn?.addEventListener("click", togglePassword);
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

import type { HealthStatusPayload, UpdateStatusPayload } from "../../api/types";
import { getHealthStatus, getUpdateStatus, startUpdate, cancelUpdate } from "../../api/settings";
import type { FeatureDepsBase } from "../feature_deps_base";
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

const POLL_INTERVAL_IDLE = 10_000;
const POLL_INTERVAL_RUNNING = 2_000;

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { els, t, escapeHtml } = ctx;

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollGeneration = 0;
  let pollingActive = false;
  let passwordVisible = false;

  function renderStatus(status: UpdateStatusPayload, health: HealthStatusPayload): void {
    const panel = els.updateStatusPanel;
    if (!panel) return;
    syncUpdateControls(els, status);
    renderUpdateStatusPanel(panel, status, health, { t, escapeHtml });
  }

  function clearPollTimer(): void {
    if (pollTimer === null) return;
    clearTimeout(pollTimer);
    pollTimer = null;
  }

  function schedulePoll(delayMs: number, generation: number): void {
    if (!pollingActive || generation !== pollGeneration) return;
    clearPollTimer();
    pollTimer = setTimeout(() => void pollStatus(generation), delayMs);
  }

  async function pollStatus(generation: number = pollGeneration): Promise<void> {
    try {
      const [status, health] = await Promise.all([getUpdateStatus(), getHealthStatus()]);
      renderStatus(status, health);
      const interval = status.state === "running" ? POLL_INTERVAL_RUNNING : POLL_INTERVAL_IDLE;
      schedulePoll(interval, generation);
    } catch {
      schedulePoll(POLL_INTERVAL_RUNNING, generation);
    }
  }

  function restartPolling(): void {
    if (!pollingActive) return;
    pollGeneration += 1;
    clearPollTimer();
    void pollStatus(pollGeneration);
  }

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
      restartPolling();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409")) {
        window.alert(t("settings.update.already_running"));
      } else {
        window.alert(`${t("settings.update.start_failed")}\n${msg}`);
      }
    }
  }

  async function handleCancel(): Promise<void> {
    try {
      await cancelUpdate();
      restartPolling();
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
    if (pollingActive) return;
    pollingActive = true;
    restartPolling();
  }

  function stopPolling(): void {
    if (!pollingActive && pollTimer === null) return;
    pollingActive = false;
    pollGeneration += 1;
    clearPollTimer();
  }

  return {
    bindUpdateHandlers,
    startPolling,
    stopPolling,
  };
}

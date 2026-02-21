import type { UiDomElements } from "../dom/ui_dom_registry";
import type { UpdateStatusPayload } from "../../api/types";
import { getUpdateStatus, startUpdate, cancelUpdate } from "../../api/settings";

export interface UpdateFeatureDeps {
  els: UiDomElements;
  t: (key: string, vars?: Record<string, any>) => string;
  escapeHtml: (value: unknown) => string;
}

export interface UpdateFeature {
  bindUpdateHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

const POLL_INTERVAL_IDLE = 10_000;
const POLL_INTERVAL_RUNNING = 2_000;

function formatTimestamp(epoch: number | null): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString();
}

export function createUpdateFeature(ctx: UpdateFeatureDeps): UpdateFeature {
  const { els, t, escapeHtml } = ctx;

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let lastStatus: UpdateStatusPayload | null = null;
  let passwordVisible = false;

  function renderStatus(status: UpdateStatusPayload): void {
    lastStatus = status;
    const panel = els.updateStatusPanel;
    if (!panel) return;

    const isRunning = status.state === "running";
    const isIdle = status.state === "idle";

    // Toggle buttons
    if (els.updateStartBtn) {
      els.updateStartBtn.hidden = isRunning;
      (els.updateStartBtn as HTMLButtonElement).disabled = isRunning;
    }
    if (els.updateCancelBtn) {
      els.updateCancelBtn.hidden = !isRunning;
    }
    // Disable form inputs while running
    if (els.updateSsidInput) (els.updateSsidInput as HTMLInputElement).disabled = isRunning;
    if (els.updatePasswordInput) (els.updatePasswordInput as HTMLInputElement).disabled = isRunning;

    if (isIdle && !status.last_success_at && !status.issues.length) {
      panel.innerHTML = "";
      return;
    }

    const stateKey = `settings.update.state.${status.state}`;
    const phaseKey = `settings.update.phase.${status.phase}`;

    const stateVariant: Record<string, string> = {
      idle: "muted",
      running: "warn",
      success: "ok",
      failed: "bad",
    };

    let html = `<div class="update-status-grid">`;

    // State + Phase
    html += `<div class="update-status-row">`;
    html += `<span class="update-label">${escapeHtml(t("settings.update.status"))}</span>`;
    html += `<span class="pill pill--${stateVariant[status.state] || "muted"}">${escapeHtml(t(stateKey))}</span>`;
    if (!isIdle) {
      html += ` <span class="subtle">${escapeHtml(t(phaseKey))}</span>`;
    }
    html += `</div>`;

    // SSID
    if (status.ssid) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.ssid_label"))}</span>`;
      html += `<span>${escapeHtml(status.ssid)}</span>`;
      html += `</div>`;
    }

    // Timestamps
    if (status.started_at) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.started_at"))}</span>`;
      html += `<span>${escapeHtml(formatTimestamp(status.started_at))}</span>`;
      html += `</div>`;
    }
    if (status.finished_at) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.finished_at"))}</span>`;
      html += `<span>${escapeHtml(formatTimestamp(status.finished_at))}</span>`;
      html += `</div>`;
    }
    if (status.last_success_at) {
      html += `<div class="update-status-row">`;
      html += `<span class="update-label">${escapeHtml(t("settings.update.last_success"))}</span>`;
      html += `<span>${escapeHtml(formatTimestamp(status.last_success_at))}</span>`;
      html += `</div>`;
    }

    html += `</div>`;

    // Issues
    if (status.issues.length) {
      html += `<div class="update-issues" style="margin-top:1rem;">`;
      html += `<strong>${escapeHtml(t("settings.update.issues"))}</strong>`;
      html += `<ul class="issue-list">`;
      for (const issue of status.issues) {
        html += `<li class="issue-item">`;
        html += `<span class="issue-phase">[${escapeHtml(issue.phase)}]</span> `;
        html += `<span class="issue-message">${escapeHtml(issue.message)}</span>`;
        if (issue.detail) {
          html += `<div class="issue-detail subtle">${escapeHtml(issue.detail)}</div>`;
        }
        html += `</li>`;
      }
      html += `</ul></div>`;
    }

    // Log tail
    if (status.log_tail.length) {
      html += `<details class="update-log" style="margin-top:1rem;">`;
      html += `<summary>${escapeHtml(t("settings.update.log"))}</summary>`;
      html += `<pre class="log-pre" style="max-height:15rem;overflow:auto;font-size:0.75rem;background:var(--bg-secondary,#1a1a2e);padding:0.5rem;border-radius:0.25rem;">`;
      for (const line of status.log_tail) {
        html += escapeHtml(line) + "\n";
      }
      html += `</pre></details>`;
    }

    panel.innerHTML = html;
  }

  async function pollStatus(): Promise<void> {
    try {
      const status = await getUpdateStatus();
      renderStatus(status);
      const interval = status.state === "running" ? POLL_INTERVAL_RUNNING : POLL_INTERVAL_IDLE;
      pollTimer = setTimeout(() => void pollStatus(), interval);
    } catch {
      // Likely disconnected (hotspot down) — retry after a delay
      pollTimer = setTimeout(() => void pollStatus(), POLL_INTERVAL_RUNNING);
    }
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
      // Clear password from input immediately after sending
      if (els.updatePasswordInput) els.updatePasswordInput.value = "";
      // Poll immediately
      void pollStatus();
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
      void pollStatus();
    } catch {
      // ignore
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
    if (pollTimer !== null) return;
    void pollStatus();
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  return {
    bindUpdateHandlers,
    startPolling,
    stopPolling,
  };
}

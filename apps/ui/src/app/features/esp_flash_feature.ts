import type { UiDomElements } from "../dom/ui_dom_registry";
import type { EspFlashStatusPayload } from "../../api/types";
import {
  cancelEspFlash,
  getEspFlashHistory,
  getEspFlashLogs,
  getEspFlashPorts,
  getEspFlashStatus,
  startEspFlash,
} from "../../api/settings";

export interface EspFlashFeatureDeps {
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
}

export interface EspFlashFeature {
  bindHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

const POLL_IDLE_MS = 4_000;
const POLL_ACTIVE_MS = 1_000;

const STATE_TO_VARIANT: Readonly<Record<string, string>> = {
  success: "ok",
  running: "warn",
  failed: "bad",
};

export function createEspFlashFeature(ctx: EspFlashFeatureDeps): EspFlashFeature {
  const { els, t, escapeHtml } = ctx;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let nextLogIndex = 0;

  async function refreshPorts(): Promise<void> {
    if (!els.espFlashPortSelect) return;
    try {
      const payload = await getEspFlashPorts();
      const options = [`<option value="__auto__">${escapeHtml(t("settings.esp_flash.auto_detect"))}</option>`];
      for (const port of payload.ports || []) {
        const label = `${port.port}${port.description ? ` — ${port.description}` : ""}`;
        options.push(`<option value="${escapeHtml(port.port)}">${escapeHtml(label)}</option>`);
      }
      els.espFlashPortSelect.innerHTML = options.join("");
    } catch {
      // Port list unavailable — keep existing options
    }
  }

  function renderStatus(status: EspFlashStatusPayload): void {
    if (els.espFlashStatusBanner) {
      // Defensively fallback to "idle" when state is missing from API response
      const safeState: string = status.state || "idle";
      const stateLabel = t(`settings.esp_flash.state.${safeState}`);
      const extra = status.error ? ` — ${status.error}` : "";
      els.espFlashStatusBanner.textContent = `${stateLabel}${extra}`;
      const variant = STATE_TO_VARIANT[safeState] || "muted";
      els.espFlashStatusBanner.className = `pill pill--${variant}`;
    }
    if (els.espFlashStartBtn) els.espFlashStartBtn.disabled = status.state === "running";
    if (els.espFlashCancelBtn) els.espFlashCancelBtn.disabled = status.state !== "running";
    if (els.espFlashPortSelect) els.espFlashPortSelect.disabled = status.state === "running";
    if (status.state !== "running") nextLogIndex = status.log_count || 0;
  }

  async function refreshLogs(status: EspFlashStatusPayload): Promise<void> {
    if (!els.espFlashLogPanel) return;
    if (status.log_count === 0) {
      els.espFlashLogPanel.textContent = "";
      nextLogIndex = 0;
      return;
    }
    const logs = await getEspFlashLogs(nextLogIndex);
    if (logs.lines.length > 0) {
      els.espFlashLogPanel.textContent += `${logs.lines.join("\n")}\n`;
      els.espFlashLogPanel.scrollTop = els.espFlashLogPanel.scrollHeight;
    }
    nextLogIndex = logs.next_index;
  }

  async function refreshHistory(): Promise<void> {
    if (!els.espFlashHistoryPanel) return;
    let payload;
    try {
      payload = await getEspFlashHistory();
    } catch {
      // History is non-critical; keep existing panel content on transient error.
      return;
    }
    const attempts = payload.attempts || [];
    if (!attempts.length) {
      els.espFlashHistoryPanel.innerHTML = `<div class="subtle">${escapeHtml(t("settings.esp_flash.no_history"))}</div>`;
      return;
    }
    const rows = attempts.map((attempt) => {
      // Defensively fallback to "idle" when state is missing from API response
      const safeState: string = attempt.state || "idle";
      const stateLabel = t(`settings.esp_flash.state.${safeState}`);
      const port = attempt.selected_port || t("settings.esp_flash.auto_detect");
      return `<li><strong>${escapeHtml(stateLabel)}</strong> — ${escapeHtml(port)}</li>`;
    });
    els.espFlashHistoryPanel.innerHTML = `<ul>${rows.join("")}</ul>`;
  }

  async function poll(): Promise<void> {
    try {
      const status = await getEspFlashStatus();
      renderStatus(status);
      await refreshLogs(status);
      await refreshHistory();
      pollTimer = setTimeout(() => void poll(), status.state === "running" ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    } catch {
      pollTimer = setTimeout(() => void poll(), POLL_ACTIVE_MS);
    }
  }

  async function onStart(): Promise<void> {
    const selected = els.espFlashPortSelect?.value || "__auto__";
    const autoDetect = selected === "__auto__";
    const port = autoDetect ? null : selected;
    try {
      await startEspFlash(port, autoDetect);
      if (els.espFlashLogPanel) els.espFlashLogPanel.textContent = "";
      nextLogIndex = 0;
      void poll();
    } catch (err) {
      window.alert(`${t("settings.esp_flash.start_failed")}\n${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function onCancel(): Promise<void> {
    try {
      await cancelEspFlash();
    } catch {
      // Cancel request may fail if the job already finished; poll to sync state.
    }
    void poll();
  }

  function bindHandlers(): void {
    els.espFlashStartBtn?.addEventListener("click", () => void onStart());
    els.espFlashCancelBtn?.addEventListener("click", () => void onCancel());
    els.espFlashRefreshPortsBtn?.addEventListener("click", () => void refreshPorts());
  }

  function startPolling(): void {
    if (pollTimer !== null) return;
    void refreshPorts();
    void poll();
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  return { bindHandlers, startPolling, stopPolling };
}

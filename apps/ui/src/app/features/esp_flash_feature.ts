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
  t: (key: string, vars?: Record<string, any>) => string;
  escapeHtml: (value: unknown) => string;
}

export interface EspFlashFeature {
  bindHandlers(): void;
  startPolling(): void;
  stopPolling(): void;
}

const POLL_IDLE_MS = 4_000;
const POLL_ACTIVE_MS = 1_000;

export function createEspFlashFeature(ctx: EspFlashFeatureDeps): EspFlashFeature {
  const { els, t, escapeHtml } = ctx;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let nextLogIndex = 0;

  async function refreshPorts(): Promise<void> {
    if (!els.espFlashPortSelect) return;
    const payload = await getEspFlashPorts();
    const options = [`<option value="__auto__">${escapeHtml(t("settings.esp_flash.auto_detect"))}</option>`];
    for (const port of payload.ports || []) {
      const label = `${port.port}${port.description ? ` — ${port.description}` : ""}`;
      options.push(`<option value="${escapeHtml(port.port)}">${escapeHtml(label)}</option>`);
    }
    els.espFlashPortSelect.innerHTML = options.join("");
  }

  function renderStatus(status: EspFlashStatusPayload): void {
    if (els.espFlashStatusBanner) {
      const stateLabel = t(`settings.esp_flash.state.${status.state}`);
      const extra = status.error ? ` — ${status.error}` : "";
      els.espFlashStatusBanner.textContent = `${stateLabel}${extra}`;
      const variant = status.state === "success" ? "ok" : status.state === "running" ? "warn" : status.state === "failed" ? "bad" : "muted";
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
    const payload = await getEspFlashHistory();
    const attempts = payload.attempts || [];
    if (!attempts.length) {
      els.espFlashHistoryPanel.innerHTML = `<div class="subtle">${escapeHtml(t("settings.esp_flash.no_history"))}</div>`;
      return;
    }
    const rows = attempts.map((attempt: any) => {
      const stateLabel = t(`settings.esp_flash.state.${attempt.state}`);
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
    await cancelEspFlash();
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

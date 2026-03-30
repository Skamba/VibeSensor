export type SettingsFeedbackTone = "info" | "error";

export interface SettingsFeedbackMessage {
  body: string;
  detail?: string;
  title?: string;
  tone?: SettingsFeedbackTone;
  compact?: boolean;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderSettingsFeedback(message: SettingsFeedbackMessage): string {
  const tone = message.tone ?? "info";
  const classNames = ["settings-feedback", `settings-feedback--${tone}`];
  if (message.compact) {
    classNames.push("settings-feedback--compact");
  }
  const titleHtml = message.title
    ? `<strong class="settings-feedback__title">${escapeHtml(message.title)}</strong>`
    : "";
  const detailHtml = message.detail
    ? `<span class="settings-feedback__detail">${escapeHtml(message.detail)}</span>`
    : "";
  return `
    <div class="${classNames.join(" ")}">
      ${titleHtml}
      <span class="settings-feedback__body">${escapeHtml(message.body)}</span>
      ${detailHtml}
    </div>
  `;
}

export function setSettingsFeedback(
  slot: HTMLElement | null,
  message: SettingsFeedbackMessage | null,
): void {
  if (!slot) {
    return;
  }
  if (!message) {
    slot.hidden = true;
    slot.innerHTML = "";
    slot.removeAttribute("aria-live");
    return;
  }
  slot.hidden = false;
  slot.setAttribute("aria-live", message.tone === "error" ? "assertive" : "polite");
  slot.innerHTML = renderSettingsFeedback(message);
}

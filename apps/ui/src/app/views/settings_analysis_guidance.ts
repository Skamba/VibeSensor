import { renderSettingsFeedback } from "./settings_feedback";

export interface SettingsAnalysisGuidanceLine {
  label: string;
  value: string;
}

export interface SettingsAnalysisGuidanceOptions {
  lines: readonly SettingsAnalysisGuidanceLine[];
  errorMessage?: string | null;
  escapeHtml: (value: unknown) => string;
}

function renderGuidanceLine(
  line: SettingsAnalysisGuidanceLine,
  escapeHtml: SettingsAnalysisGuidanceOptions["escapeHtml"],
): string {
  return `<span class="settings-field-guidance__line"><span class="settings-field-guidance__label">${escapeHtml(line.label)}</span> ${escapeHtml(line.value)}</span>`;
}

export function setSettingsAnalysisGuidance(
  slot: HTMLElement | null,
  options: SettingsAnalysisGuidanceOptions,
): void {
  if (!slot) {
    return;
  }
  const guidanceHtml = options.lines
    .map((line) => renderGuidanceLine(line, options.escapeHtml))
    .join("");
  const errorHtml = options.errorMessage
    ? renderSettingsFeedback({
        tone: "error",
        body: options.errorMessage,
        compact: true,
      })
    : "";
  slot.innerHTML = `<span class="settings-field-guidance__stack">${guidanceHtml}</span>${errorHtml}`;
}

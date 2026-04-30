export type SettingsFeedbackTone = "info" | "error";

export interface SettingsFeedbackMessage {
  body: string;
  detail?: string;
  title?: string;
  tone?: SettingsFeedbackTone;
  compact?: boolean;
}

export interface SettingsFeedbackAttrs {
  class: "settings-feedback";
  "data-tone": SettingsFeedbackTone;
  "data-compact"?: "true";
}

export function settingsFeedbackAttrs(
  message: SettingsFeedbackMessage,
): SettingsFeedbackAttrs {
  const tone = message.tone ?? "info";
  return {
    class: "settings-feedback",
    "data-tone": tone,
    "data-compact": message.compact ? "true" : undefined,
  };
}

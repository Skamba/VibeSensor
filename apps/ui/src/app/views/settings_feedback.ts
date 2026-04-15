export type SettingsFeedbackTone = "info" | "error";

export interface SettingsFeedbackMessage {
  body: string;
  detail?: string;
  title?: string;
  tone?: SettingsFeedbackTone;
  compact?: boolean;
}

export function settingsFeedbackClassName(message: SettingsFeedbackMessage): string {
  const tone = message.tone ?? "info";
  const classNames = ["settings-feedback", `settings-feedback--${tone}`];
  if (message.compact) {
    classNames.push("settings-feedback--compact");
  }
  return classNames.join(" ");
}

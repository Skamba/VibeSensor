import { requiredById } from "./dom_query";

const SETTINGS_SHELL_OWNER = "Settings shell";
const SETTINGS_SHELL_HOST_ID = "settingsShellRoot";

export function getUiSettingsShellHost(): HTMLElement {
  return requiredById<HTMLElement>(SETTINGS_SHELL_HOST_ID, SETTINGS_SHELL_OWNER);
}

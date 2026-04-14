import { queryRequiredAll } from "./dom_query";

const SETTINGS_OWNER = "Settings feature";

export interface UiSettingsDom {
  settingsTabs: HTMLElement[];
  settingsTabPanels: HTMLElement[];
}

export function createUiSettingsDom(): UiSettingsDom {
  return {
    settingsTabs: queryRequiredAll<HTMLElement>(
      ".settings-tab",
      SETTINGS_OWNER,
    ),
    settingsTabPanels: queryRequiredAll<HTMLElement>(
      ".settings-tab-panel",
      SETTINGS_OWNER,
    ),
  };
}

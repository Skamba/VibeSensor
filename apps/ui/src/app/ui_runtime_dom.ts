import { createUiCarsDom, type UiCarsDom } from "./dom/cars_dom";
import { createUiHistoryDom, type UiHistoryDom } from "./dom/history_dom";
import { createUiRealtimeDom, type UiRealtimeDom } from "./dom/realtime_dom";
import { createUiSettingsDom, type UiSettingsDom } from "./dom/settings_dom";
import { createUiShellDom, type UiShellDom } from "./dom/shell_dom";
import { createUiSpectrumDom, type UiSpectrumDom } from "./dom/spectrum_dom";

export interface UiRuntimeDom {
  shell: UiShellDom;
  spectrum: UiSpectrumDom;
  realtime: UiRealtimeDom;
  history: UiHistoryDom;
  settings: UiSettingsDom;
  cars: UiCarsDom;
}

export function createUiRuntimeDom(): UiRuntimeDom {
  return {
    shell: createUiShellDom(),
    spectrum: createUiSpectrumDom(),
    realtime: createUiRealtimeDom(),
    history: createUiHistoryDom(),
    settings: createUiSettingsDom(),
    cars: createUiCarsDom(),
  };
}

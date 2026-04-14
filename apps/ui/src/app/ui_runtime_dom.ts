import { createUiShellDom, type UiShellDom } from "./dom/shell_dom";
import { createUiSpectrumDom, type UiSpectrumDom } from "./dom/spectrum_dom";

export interface UiRuntimeDom {
  shell: UiShellDom;
  spectrum: UiSpectrumDom;
}

export function createUiRuntimeDom(): UiRuntimeDom {
  return {
    shell: createUiShellDom(),
    spectrum: createUiSpectrumDom(),
  };
}

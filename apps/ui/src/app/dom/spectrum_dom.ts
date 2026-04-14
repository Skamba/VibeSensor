import { getById, requiredById } from "./dom_query";

const SPECTRUM_OWNER = "Spectrum UI";

export interface UiSpectrumDom {
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement;
}

export function createUiSpectrumDom(): UiSpectrumDom {
  return {
    specChartWrap: getById<HTMLElement>("specChartWrap"),
    specChart: requiredById<HTMLElement>("specChart", SPECTRUM_OWNER),
  };
}

export function getUiSpectrumPanelHost(): HTMLElement {
  return requiredById<HTMLElement>("spectrumPanelRoot", SPECTRUM_OWNER);
}

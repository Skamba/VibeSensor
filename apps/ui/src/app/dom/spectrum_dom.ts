import { getById, requiredById } from "./dom_query";

const SPECTRUM_OWNER = "Spectrum UI";

export interface UiSpectrumDom {
  specChartWrap: HTMLElement | null;
  specChart: HTMLElement;
  spectrumOverlay: HTMLElement | null;
  spectrumInspector: HTMLElement | null;
  legend: HTMLElement | null;
  bandLegend: HTMLElement | null;
  spectrumBandToggle: HTMLButtonElement | null;
}

export function createUiSpectrumDom(): UiSpectrumDom {
  return {
    specChartWrap: getById<HTMLElement>("specChartWrap"),
    specChart: requiredById<HTMLElement>("specChart", SPECTRUM_OWNER),
    spectrumOverlay: getById<HTMLElement>("spectrumOverlay"),
    spectrumInspector: getById<HTMLElement>("spectrumInspector"),
    legend: getById<HTMLElement>("legend"),
    bandLegend: getById<HTMLElement>("bandLegend"),
    spectrumBandToggle: getById<HTMLButtonElement>("spectrumBandToggle"),
  };
}

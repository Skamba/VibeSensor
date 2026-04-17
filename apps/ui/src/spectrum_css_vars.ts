import { computed, signal } from "./app/ui_signals";

export interface SpectrumCssVars {
  surface: string;
  muted: string;
  border: string;
  tooltipBg: string;
  tooltipFg: string;
}

const DEFAULT_SPECTRUM_CSS_VARS: Readonly<SpectrumCssVars> = Object.freeze({
  surface: "#f8f9fb",
  muted: "#5a6b82",
  border: "#d7e1ee",
  tooltipBg: "rgba(15, 23, 42, 0.88)",
  tooltipFg: "#f8f9fb",
});

const THEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";
const spectrumCssVarsVersion = signal(0);
const spectrumCssVars = computed<Readonly<SpectrumCssVars>>(() => {
  spectrumCssVarsVersion.value;
  return readSpectrumCssVars();
});
let spectrumCssVarsThemeListenerInitialized = false;

function readSpectrumCssVars(): Readonly<SpectrumCssVars> {
  const rootStyle = getComputedStyle(document.documentElement);
  return Object.freeze({
    surface: rootStyle.getPropertyValue("--surface").trim() || DEFAULT_SPECTRUM_CSS_VARS.surface,
    muted: rootStyle.getPropertyValue("--muted").trim() || DEFAULT_SPECTRUM_CSS_VARS.muted,
    border: rootStyle.getPropertyValue("--border").trim() || DEFAULT_SPECTRUM_CSS_VARS.border,
    tooltipBg: rootStyle.getPropertyValue("--tooltip-bg").trim()
      || DEFAULT_SPECTRUM_CSS_VARS.tooltipBg,
    tooltipFg: rootStyle.getPropertyValue("--tooltip-fg").trim()
      || DEFAULT_SPECTRUM_CSS_VARS.tooltipFg,
  });
}

export function getSpectrumCssVars(): Readonly<SpectrumCssVars> {
  ensureSpectrumCssVarsThemeTracking();
  return spectrumCssVars.value;
}

export function refreshSpectrumCssVars(): Readonly<SpectrumCssVars> {
  ensureSpectrumCssVarsThemeTracking();
  spectrumCssVarsVersion.value += 1;
  return spectrumCssVars.value;
}

function ensureSpectrumCssVarsThemeTracking(): void {
  if (spectrumCssVarsThemeListenerInitialized) {
    return;
  }
  if (typeof globalThis.matchMedia !== "function") {
    return;
  }
  spectrumCssVarsThemeListenerInitialized = true;
  const mediaQuery = globalThis.matchMedia(THEME_MEDIA_QUERY);
  const refresh = () => {
    spectrumCssVarsVersion.value += 1;
  };
  mediaQuery.addEventListener("change", refresh);
}

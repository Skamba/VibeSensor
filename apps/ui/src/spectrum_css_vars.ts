import { computed, effect, signal } from "./app/ui_signals";

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
let cachedSpectrumCssVars: Readonly<SpectrumCssVars> | null = null;
let stopSpectrumCssVarsThemeTracking: (() => void) | null = null;

/**
 * Theme tokens the canvas chart reads. `--surface`, `--muted` and `--border`
 * were alias tokens dropped in the token cleanup; reading them silently fell
 * back to the light defaults, so the dark theme drew light grid lines and
 * axis text.
 */
const SPECTRUM_CSS_VAR_TOKENS: Readonly<Record<keyof SpectrumCssVars, string>> =
  Object.freeze({
    surface: "--md-sys-color-surface-container",
    muted: "--md-sys-color-on-surface-variant",
    border: "--chart-grid",
    tooltipBg: "--tooltip-bg",
    tooltipFg: "--tooltip-fg",
  });

function readSpectrumCssVars(): Readonly<SpectrumCssVars> {
  const rootStyle = getComputedStyle(document.documentElement);
  const read = (key: keyof SpectrumCssVars): string =>
    rootStyle.getPropertyValue(SPECTRUM_CSS_VAR_TOKENS[key]).trim() ||
    DEFAULT_SPECTRUM_CSS_VARS[key];
  const next: SpectrumCssVars = {
    surface: read("surface"),
    muted: read("muted"),
    border: read("border"),
    tooltipBg: read("tooltipBg"),
    tooltipFg: read("tooltipFg"),
  };
  if (
    cachedSpectrumCssVars &&
    cachedSpectrumCssVars.surface === next.surface &&
    cachedSpectrumCssVars.muted === next.muted &&
    cachedSpectrumCssVars.border === next.border &&
    cachedSpectrumCssVars.tooltipBg === next.tooltipBg &&
    cachedSpectrumCssVars.tooltipFg === next.tooltipFg
  ) {
    return cachedSpectrumCssVars;
  }
  cachedSpectrumCssVars = Object.freeze(next);
  return cachedSpectrumCssVars;
}

export function getSpectrumCssVars(): Readonly<SpectrumCssVars> {
  ensureSpectrumCssVarsThemeTracking();
  return spectrumCssVars.value;
}

function refreshSpectrumCssVars(): Readonly<SpectrumCssVars> {
  ensureSpectrumCssVarsThemeTracking();
  spectrumCssVarsVersion.value += 1;
  return spectrumCssVars.value;
}

function ensureSpectrumCssVarsThemeTracking(): void {
  if (stopSpectrumCssVarsThemeTracking) {
    return;
  }
  if (typeof globalThis.matchMedia !== "function") {
    return;
  }
  stopSpectrumCssVarsThemeTracking = effect(() => {
    const mediaQuery = globalThis.matchMedia(THEME_MEDIA_QUERY);
    const refresh = () => {
      refreshSpectrumCssVars();
    };
    mediaQuery.addEventListener("change", refresh);
    return () => {
      mediaQuery.removeEventListener("change", refresh);
      stopSpectrumCssVarsThemeTracking = null;
    };
  });
}

import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "../../api/settings";
import type { UiDomElements } from "../ui_dom_registry";
import type { AppState } from "../ui_app_state";

export interface UiShellPreferencesModuleDeps {
  state: AppState;
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
  normalizeLanguage: (lang: string) => string;
  applyLanguage: (forceReloadInsights?: boolean) => void;
  renderSpeedReadout: () => void;
}

export interface UiShellPreferencesModule {
  bindHandlers(): void;
  hydratePersistedPreferences(): Promise<void>;
  saveLanguage(lang: string): Promise<void>;
  saveSpeedUnit(unit: string): Promise<void>;
}

export function createUiShellPreferencesModule(
  ctx: UiShellPreferencesModuleDeps,
): UiShellPreferencesModule {
  const { state, els } = ctx;

  function normalizeSpeedUnit(raw: string): string {
    return raw === "mps" ? "mps" : "kmh";
  }

  async function hydratePersistedPreferences(): Promise<void> {
    try {
      const languageResponse = await getSettingsLanguage();
      if (languageResponse?.language) {
        state.lang = ctx.normalizeLanguage(languageResponse.language);
        ctx.applyLanguage(true);
      }
    } catch (error) {
      console.warn("Failed to load persisted language", error);
    }
    try {
      const speedUnitResponse = await getSettingsSpeedUnit();
      if (speedUnitResponse?.speedUnit) {
        state.speedUnit = normalizeSpeedUnit(speedUnitResponse.speedUnit);
        if (els.speedUnitSelect) {
          els.speedUnitSelect.value = state.speedUnit;
        }
        ctx.renderSpeedReadout();
      }
    } catch (error) {
      console.warn("Failed to load persisted speed unit", error);
    }
  }

  async function saveLanguage(lang: string): Promise<void> {
    const previousLang = state.lang;
    const nextLang = ctx.normalizeLanguage(lang);
    try {
      const payload = await setSettingsLanguage(nextLang);
      state.lang = ctx.normalizeLanguage(payload?.language || nextLang);
      if (els.languageSelect) {
        els.languageSelect.value = state.lang;
      }
      ctx.applyLanguage(true);
    } catch (error) {
      if (els.languageSelect) {
        els.languageSelect.value = previousLang;
      }
      window.alert(error instanceof Error ? error.message : ctx.t("settings.save_failed"));
    }
  }

  async function saveSpeedUnit(unit: string): Promise<void> {
    const previousUnit = state.speedUnit;
    const nextUnit = normalizeSpeedUnit(unit);
    try {
      const payload = await setSettingsSpeedUnit(nextUnit);
      state.speedUnit = normalizeSpeedUnit(payload?.speedUnit || nextUnit);
      if (els.speedUnitSelect) {
        els.speedUnitSelect.value = state.speedUnit;
      }
      ctx.renderSpeedReadout();
    } catch (error) {
      if (els.speedUnitSelect) {
        els.speedUnitSelect.value = previousUnit;
      }
      window.alert(error instanceof Error ? error.message : ctx.t("settings.save_failed"));
    }
  }

  function bindHandlers(): void {
    const languageSelect = els.languageSelect;
    if (languageSelect) {
      languageSelect.value = state.lang;
      languageSelect.addEventListener("change", () => {
        void saveLanguage(languageSelect.value);
      });
    }

    const speedUnitSelect = els.speedUnitSelect;
    if (speedUnitSelect) {
      speedUnitSelect.value = state.speedUnit;
      speedUnitSelect.addEventListener("change", () => {
        void saveSpeedUnit(speedUnitSelect.value);
      });
    }
  }

  return {
    bindHandlers,
    hydratePersistedPreferences,
    saveLanguage,
    saveSpeedUnit,
  };
}

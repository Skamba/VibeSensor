import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "../../api/settings";
import type { UiShellDom } from "../dom/shell_dom";
import type { ShellState } from "../ui_app_state";
import { setSettingsFeedback } from "../views/settings_feedback";

export interface UiShellPreferencesModuleDeps {
  shell: ShellState;
  dom: UiShellDom;
  t: (key: string, vars?: Record<string, unknown>) => string;
  normalizeLanguage: (lang: string) => string;
  applyLanguage: (forceReloadInsights?: boolean) => void;
  renderSpeedReadout: () => void;
  showError: (message: string) => void;
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
  const { shell, dom: els } = ctx;

  function normalizeSpeedUnit(raw: string): string {
    return raw === "mps" ? "mps" : "kmh";
  }

  function syncSelectValue(select: HTMLSelectElement | null, value: string): void {
    if (select) {
      select.value = value;
    }
  }

  function optionLabel(select: HTMLSelectElement | null, value: string): string {
    return Array.from(select?.options ?? []).find((option) => option.value === value)?.textContent?.trim() ?? value;
  }

  function clearPreferenceFeedback(select: HTMLSelectElement | null, feedback: HTMLElement | null): void {
    select?.removeAttribute("aria-invalid");
    select?.removeAttribute("aria-describedby");
    setSettingsFeedback(feedback, null);
  }

  function showPreferenceFeedback(
    select: HTMLSelectElement | null,
    feedback: HTMLElement | null,
    label: string,
    activeValue: string,
    error: unknown,
  ): void {
    if (feedback?.id) {
      select?.setAttribute("aria-describedby", feedback.id);
    }
    select?.setAttribute("aria-invalid", "true");
    setSettingsFeedback(feedback, {
      tone: "error",
      body: ctx.t("settings.preference.save_failed_active", {
        label,
        value: activeValue,
      }),
      detail: error instanceof Error ? error.message : ctx.t("settings.save_failed"),
      compact: true,
    });
  }

  function applyLanguageValue(rawLanguage: string): void {
    shell.lang = ctx.normalizeLanguage(rawLanguage);
    syncSelectValue(els.languageSelect, shell.lang);
  }

  function applySpeedUnitValue(rawUnit: string): void {
    shell.speedUnit = normalizeSpeedUnit(rawUnit);
    syncSelectValue(els.speedUnitSelect, shell.speedUnit);
  }

  async function hydratePersistedPreferences(): Promise<void> {
    try {
      const languageResponse = await getSettingsLanguage();
      if (languageResponse?.language) {
        applyLanguageValue(languageResponse.language);
        ctx.applyLanguage(true);
      }
    } catch (error) {
      console.warn("Failed to load persisted language", error);
    }
    try {
      const speedUnitResponse = await getSettingsSpeedUnit();
      if (speedUnitResponse?.speed_unit) {
        applySpeedUnitValue(speedUnitResponse.speed_unit);
        ctx.renderSpeedReadout();
      }
    } catch (error) {
      console.warn("Failed to load persisted speed unit", error);
    }
  }

  async function saveLanguage(lang: string): Promise<void> {
    const previousLang = shell.lang;
    const nextLang = ctx.normalizeLanguage(lang);
    clearPreferenceFeedback(els.languageSelect, els.languageFeedback);
    try {
      const payload = await setSettingsLanguage(nextLang);
      applyLanguageValue(payload?.language || nextLang);
      ctx.applyLanguage(true);
    } catch (error) {
      syncSelectValue(els.languageSelect, previousLang);
      showPreferenceFeedback(
        els.languageSelect,
        els.languageFeedback,
        ctx.t("settings.language"),
        optionLabel(els.languageSelect, previousLang),
        error,
      );
    }
  }

  async function saveSpeedUnit(unit: string): Promise<void> {
    const previousUnit = shell.speedUnit;
    const nextUnit = normalizeSpeedUnit(unit);
    clearPreferenceFeedback(els.speedUnitSelect, els.speedUnitFeedback);
    try {
      const payload = await setSettingsSpeedUnit(nextUnit);
      applySpeedUnitValue(payload?.speed_unit || nextUnit);
      ctx.renderSpeedReadout();
    } catch (error) {
      syncSelectValue(els.speedUnitSelect, previousUnit);
      showPreferenceFeedback(
        els.speedUnitSelect,
        els.speedUnitFeedback,
        ctx.t("speed.unit"),
        optionLabel(els.speedUnitSelect, previousUnit),
        error,
      );
    }
  }

  function bindHandlers(): void {
    const languageSelect = els.languageSelect;
    if (languageSelect) {
      languageSelect.value = shell.lang;
      languageSelect.addEventListener("change", () => {
        clearPreferenceFeedback(els.languageSelect, els.languageFeedback);
        void saveLanguage(languageSelect.value);
      });
    }

    const speedUnitSelect = els.speedUnitSelect;
    if (speedUnitSelect) {
      speedUnitSelect.value = shell.speedUnit;
      speedUnitSelect.addEventListener("change", () => {
        clearPreferenceFeedback(els.speedUnitSelect, els.speedUnitFeedback);
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

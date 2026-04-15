import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "../../api/settings";
import type { SettingsFeedbackMessage } from "../views/settings_feedback";
import type { ShellState } from "../ui_app_state";

export interface UiShellPreferencesModule {
  clearPreferenceFeedback(): void;
  getLanguageFeedback(): SettingsFeedbackMessage | null;
  getSelectedLanguage(): string;
  getSelectedSpeedUnit(): string;
  getSpeedUnitFeedback(): SettingsFeedbackMessage | null;
  hydratePersistedPreferences(): Promise<void>;
  saveLanguage(lang: string): Promise<void>;
  saveSpeedUnit(unit: string): Promise<void>;
}

type UiShellPreferencesDeps = {
  applyLanguage: (forceReloadInsights?: boolean) => void;
  normalizeLanguage: (value: string | null | undefined) => string;
  onChanged?: () => void;
  renderSpeedReadout: () => void;
  shell: ShellState;
  t: (key: string, vars?: Record<string, unknown>) => string;
};

export function createUiShellPreferencesModule(
  deps: UiShellPreferencesDeps,
): UiShellPreferencesModule {
  let languageFeedback: SettingsFeedbackMessage | null = null;
  let speedUnitFeedback: SettingsFeedbackMessage | null = null;
  let selectedLanguage = deps.shell.lang;
  let selectedSpeedUnit = deps.shell.speedUnit;

  function notifyChanged(): void {
    deps.onChanged?.();
  }

  function speedUnitLabel(value: string): string {
    return deps.t(value === "mps" ? "speed.unit.mps" : "speed.unit.kmh");
  }

  function normalizeSpeedUnit(raw: string): string {
    return raw === "mps" ? "mps" : "kmh";
  }

  function languageLabel(value: string): string {
    return value === "nl" ? "Nederlands" : "English";
  }

  function applyLanguageValue(rawLanguage: string): void {
    deps.shell.lang = deps.normalizeLanguage(rawLanguage);
    selectedLanguage = deps.shell.lang;
  }

  function applySpeedUnitValue(rawUnit: string): void {
    deps.shell.speedUnit = normalizeSpeedUnit(rawUnit);
    selectedSpeedUnit = deps.shell.speedUnit;
  }

  function buildSaveFailureFeedback(
    label: string,
    activeValue: string,
    error: unknown,
  ): SettingsFeedbackMessage {
    return {
      body: deps.t("settings.preference.save_failed_active", {
        label,
        value: activeValue,
      }),
      compact: true,
      detail: error instanceof Error ? error.message : deps.t("settings.save_failed"),
      tone: "error",
    };
  }

  return {
    clearPreferenceFeedback() {
      languageFeedback = null;
      speedUnitFeedback = null;
      notifyChanged();
    },
    getLanguageFeedback() {
      return languageFeedback;
    },
    getSelectedLanguage() {
      return selectedLanguage;
    },
    getSelectedSpeedUnit() {
      return selectedSpeedUnit;
    },
    getSpeedUnitFeedback() {
      return speedUnitFeedback;
    },
    async hydratePersistedPreferences() {
      try {
        const languageResponse = await getSettingsLanguage();
        if (languageResponse?.language) {
          applyLanguageValue(languageResponse.language);
          deps.applyLanguage(true);
        }
      } catch (error) {
        console.warn("Failed to load persisted language", error);
      }
      try {
        const speedUnitResponse = await getSettingsSpeedUnit();
        if (speedUnitResponse?.speed_unit) {
          applySpeedUnitValue(speedUnitResponse.speed_unit);
          deps.renderSpeedReadout();
        }
      } catch (error) {
        console.warn("Failed to load persisted speed unit", error);
      }
    },
    async saveLanguage(lang) {
      const nextLanguage = deps.normalizeLanguage(lang);
      const previousLanguage = deps.shell.lang;
      languageFeedback = null;
      selectedLanguage = nextLanguage;
      notifyChanged();
      try {
        const payload = await setSettingsLanguage(nextLanguage);
        applyLanguageValue(payload?.language || nextLanguage);
        deps.applyLanguage(true);
      } catch (error) {
        selectedLanguage = previousLanguage;
        languageFeedback = buildSaveFailureFeedback(
          deps.t("settings.language"),
          languageLabel(previousLanguage),
          error,
        );
        notifyChanged();
      }
    },
    async saveSpeedUnit(unit) {
      const nextUnit = normalizeSpeedUnit(unit);
      const previousUnit = deps.shell.speedUnit;
      speedUnitFeedback = null;
      selectedSpeedUnit = nextUnit;
      notifyChanged();
      try {
        const payload = await setSettingsSpeedUnit(nextUnit);
        applySpeedUnitValue(payload?.speed_unit || nextUnit);
        deps.renderSpeedReadout();
      } catch (error) {
        selectedSpeedUnit = previousUnit;
        speedUnitFeedback = buildSaveFailureFeedback(
          deps.t("speed.unit"),
          speedUnitLabel(previousUnit),
          error,
        );
        notifyChanged();
      }
    },
  };
}

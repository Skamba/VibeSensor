import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "../../api/settings";
import type { SettingsFeedbackMessage } from "../views/settings_feedback";
import type { ShellState } from "../ui_app_state";
import { signal, type ReadonlySignal } from "../ui_signals";

export interface UiShellPreferencesModule {
  readonly languageFeedback: ReadonlySignal<SettingsFeedbackMessage | null>;
  readonly selectedLanguage: ReadonlySignal<string>;
  readonly selectedSpeedUnit: ReadonlySignal<string>;
  readonly speedUnitFeedback: ReadonlySignal<SettingsFeedbackMessage | null>;
  clearPreferenceFeedback(): void;
  hydratePersistedPreferences(): Promise<void>;
  saveLanguage(lang: string): Promise<void>;
  saveSpeedUnit(unit: string): Promise<void>;
}

type UiShellPreferencesDeps = {
  applyLanguage: (forceReloadInsights?: boolean) => void;
  normalizeLanguage: (value: string | null | undefined) => string;
  renderSpeedReadout: () => void;
  shell: ShellState;
  t: (key: string, vars?: Record<string, unknown>) => string;
};

export function createUiShellPreferencesModule(
  deps: UiShellPreferencesDeps,
): UiShellPreferencesModule {
  const languageFeedback = signal<SettingsFeedbackMessage | null>(null);
  const speedUnitFeedback = signal<SettingsFeedbackMessage | null>(null);
  const selectedLanguage = signal(deps.shell.lang);
  const selectedSpeedUnit = signal(deps.shell.speedUnit);

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
    selectedLanguage.value = deps.shell.lang;
  }

  function applySpeedUnitValue(rawUnit: string): void {
    deps.shell.speedUnit = normalizeSpeedUnit(rawUnit);
    selectedSpeedUnit.value = deps.shell.speedUnit;
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
    languageFeedback,
    selectedLanguage,
    selectedSpeedUnit,
    speedUnitFeedback,
    clearPreferenceFeedback() {
      languageFeedback.value = null;
      speedUnitFeedback.value = null;
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
      languageFeedback.value = null;
      selectedLanguage.value = nextLanguage;
      try {
        const payload = await setSettingsLanguage(nextLanguage);
        applyLanguageValue(payload?.language || nextLanguage);
        deps.applyLanguage(true);
      } catch (error) {
        selectedLanguage.value = previousLanguage;
        languageFeedback.value = buildSaveFailureFeedback(
          deps.t("settings.language"),
          languageLabel(previousLanguage),
          error,
        );
      }
    },
    async saveSpeedUnit(unit) {
      const nextUnit = normalizeSpeedUnit(unit);
      const previousUnit = deps.shell.speedUnit;
      speedUnitFeedback.value = null;
      selectedSpeedUnit.value = nextUnit;
      try {
        const payload = await setSettingsSpeedUnit(nextUnit);
        applySpeedUnitValue(payload?.speed_unit || nextUnit);
        deps.renderSpeedReadout();
      } catch (error) {
        selectedSpeedUnit.value = previousUnit;
        speedUnitFeedback.value = buildSaveFailureFeedback(
          deps.t("speed.unit"),
          speedUnitLabel(previousUnit),
          error,
        );
      }
    },
  };
}

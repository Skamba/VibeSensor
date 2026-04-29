import type { QueryClient } from "@tanstack/query-core";

import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "../../api";
import { uiLogger } from "../../ui_logger";
import { serverStateQueryKeys } from "../features/server_state_query_keys";
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
  normalizeLanguage: (value: string | null | undefined) => string;
  prepareLanguage: (value: string) => Promise<void>;
  queryClient: QueryClient;
  shell: ShellState;
  t: (key: string, vars?: Record<string, unknown>) => string;
};

const PERSISTED_SHELL_PREFERENCES_STALE_TIME_MS = 5 * 60 * 1000;

export function createUiShellPreferencesModule(
  deps: UiShellPreferencesDeps,
): UiShellPreferencesModule {
  const languageFeedback = signal<SettingsFeedbackMessage | null>(null);
  const speedUnitFeedback = signal<SettingsFeedbackMessage | null>(null);
  const selectedLanguage = signal(deps.shell.lang.value);
  const selectedSpeedUnit = signal(deps.shell.speedUnit.value);

  function speedUnitLabel(value: string): string {
    return deps.t(value === "mps" ? "speed.unit.mps" : "speed.unit.kmh");
  }

  function normalizeSpeedUnit(raw: string): string {
    return raw === "mps" ? "mps" : "kmh";
  }

  function languageLabel(value: string): string {
    return value === "nl" ? "Nederlands" : "English";
  }

  async function applyLanguageValue(rawLanguage: string): Promise<void> {
    const nextLanguage = deps.normalizeLanguage(rawLanguage);
    await deps.prepareLanguage(nextLanguage);
    deps.shell.lang.value = nextLanguage;
    selectedLanguage.value = nextLanguage;
  }

  function applySpeedUnitValue(rawUnit: string): void {
    deps.shell.speedUnit.value = normalizeSpeedUnit(rawUnit);
    selectedSpeedUnit.value = deps.shell.speedUnit.value;
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
      detail:
        error instanceof Error ? error.message : deps.t("settings.save_failed"),
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
      const [languageResult, speedUnitResult] = await Promise.allSettled([
        deps.queryClient.fetchQuery({
          queryFn: () => getSettingsLanguage(),
          queryKey: serverStateQueryKeys.settings.language(),
          staleTime: PERSISTED_SHELL_PREFERENCES_STALE_TIME_MS,
        }),
        deps.queryClient.fetchQuery({
          queryFn: () => getSettingsSpeedUnit(),
          queryKey: serverStateQueryKeys.settings.speedUnit(),
          staleTime: PERSISTED_SHELL_PREFERENCES_STALE_TIME_MS,
        }),
      ]);
      if (
        languageResult.status === "fulfilled" &&
        languageResult.value?.language
      ) {
        await applyLanguageValue(languageResult.value.language);
      } else if (languageResult.status === "rejected") {
        uiLogger.warn(
          "Failed to load persisted language",
          languageResult.reason,
        );
      }
      if (
        speedUnitResult.status === "fulfilled" &&
        speedUnitResult.value?.speed_unit
      ) {
        applySpeedUnitValue(speedUnitResult.value.speed_unit);
      } else if (speedUnitResult.status === "rejected") {
        uiLogger.warn(
          "Failed to load persisted speed unit",
          speedUnitResult.reason,
        );
      }
    },
    async saveLanguage(lang) {
      const nextLanguage = deps.normalizeLanguage(lang);
      const previousLanguage = deps.shell.lang.value;
      languageFeedback.value = null;
      selectedLanguage.value = nextLanguage;
      try {
        const payload = await setSettingsLanguage(nextLanguage);
        const resolvedLanguage = payload?.language || nextLanguage;
        deps.queryClient.setQueryData(
          serverStateQueryKeys.settings.language(),
          { language: resolvedLanguage },
        );
        await applyLanguageValue(resolvedLanguage);
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
      const previousUnit = deps.shell.speedUnit.value;
      speedUnitFeedback.value = null;
      selectedSpeedUnit.value = nextUnit;
      try {
        const payload = await setSettingsSpeedUnit(nextUnit);
        const resolvedSpeedUnit = payload?.speed_unit || nextUnit;
        deps.queryClient.setQueryData(
          serverStateQueryKeys.settings.speedUnit(),
          { speed_unit: resolvedSpeedUnit },
        );
        applySpeedUnitValue(resolvedSpeedUnit);
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

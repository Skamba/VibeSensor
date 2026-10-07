import { signal } from "@preact/signals";

import {
  getSettingsLanguage,
  getSettingsSpeedUnit,
  setSettingsLanguage,
  setSettingsSpeedUnit,
} from "./api/settings";
import type { Feedback } from "./components/feedback";
import { type SpeedUnit, speedUnitKey } from "./format";
import { lang, normalizeLang, setLanguage, t } from "./i18n";
import { uiLogger } from "./ui_logger";

/** Shell-wide state: navigation, error banner, confirmation, preferences. */

export const VIEW_IDS = [
  "dashboardView",
  "historyView",
  "settingsView",
] as const;
export type ViewId = (typeof VIEW_IDS)[number];

export const SETTINGS_TAB_IDS = [
  "carTab",
  "analysisTab",
  "speedSourceTab",
  "sensorsTab",
  "internetTab",
  "updateTab",
  "espFlashTab",
  "generalTab",
] as const;
export type SettingsTabId = (typeof SETTINGS_TAB_IDS)[number];

export function isDemoMode(): boolean {
  return new URLSearchParams(globalThis.location?.search).has("demo");
}

export const activeView = signal<ViewId>("dashboardView");
export const settingsTab = signal<SettingsTabId>("carTab");
export const errorBanner = signal<string | null>(null);
export const speedUnit = signal<SpeedUnit>("kmh");

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

// --- Navigation -----------------------------------------------------------

const viewLoaders = new Map<ViewId, Array<() => Promise<unknown>>>();
let navigationToken = 0;

/** Registers data a view needs before it is shown (latest navigation wins). */
export function onViewEnter(view: ViewId, load: () => Promise<unknown>): void {
  viewLoaders.set(view, [...(viewLoaders.get(view) ?? []), load]);
}

export function navigate(view: ViewId, tab?: SettingsTabId): void {
  if (tab) {
    settingsTab.value = tab;
  }
  const show = () => {
    activeView.value = view;
    // A deep link (e.g. Live's "Place 3 sensors") opens its tab at the top,
    // not at the scroll offset the page it came from had.
    if (tab) {
      globalThis.scrollTo?.({ top: 0 });
    }
  };
  const token = ++navigationToken;
  const loaders = viewLoaders.get(view);
  if (!loaders) {
    show();
    return;
  }
  Promise.all(loaders.map((load) => load())).then(
    () => {
      if (token === navigationToken) {
        show();
      }
    },
    (error: unknown) => {
      if (token === navigationToken) {
        showError(errorMessage(error, t("status.view_load_failed")));
      }
    },
  );
}

// --- Error banner and confirmation -----------------------------------------

const ERROR_BANNER_MS = 5000;
let errorBannerTimer: ReturnType<typeof setTimeout> | undefined;

export function showError(message: string): void {
  clearTimeout(errorBannerTimer);
  errorBanner.value = message;
  errorBannerTimer = setTimeout(() => {
    errorBanner.value = null;
  }, ERROR_BANNER_MS);
}

interface PendingConfirmation {
  message: string;
  resolve(confirmed: boolean): void;
}

const confirmationQueue: PendingConfirmation[] = [];
export const confirmation = signal<PendingConfirmation | null>(null);

/** Asks the user to confirm `message`; requests queue one dialog at a time. */
export function requestConfirmation(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    confirmationQueue.push({ message, resolve });
    if (confirmation.value === null) {
      confirmation.value = confirmationQueue.shift() ?? null;
    }
  });
}

export function settleConfirmation(confirmed: boolean): void {
  const current = confirmation.value;
  if (current === null) {
    return;
  }
  confirmation.value = confirmationQueue.shift() ?? null;
  current.resolve(confirmed);
}

// --- First-load hotspot hint ------------------------------------------------

const HOTSPOT_HINT_KEY = "vibesensor.hotspotHintDismissed";

function hotspotHintDismissed(): boolean {
  try {
    return globalThis.localStorage?.getItem(HOTSPOT_HINT_KEY) === "1";
  } catch {
    return false;
  }
}

/** Until dismissed: the phone may report "no internet" on the hotspot; stay connected. */
export const hotspotHintVisible = signal<boolean>(
  !isDemoMode() && !hotspotHintDismissed(),
);

export function dismissHotspotHint(): void {
  hotspotHintVisible.value = false;
  try {
    globalThis.localStorage?.setItem(HOTSPOT_HINT_KEY, "1");
  } catch {
    // Remembering the dismissal is a per-browser convenience only.
  }
}

// --- Preferences (language and speed unit) ---------------------------------

/** What the selects show; differs from the active value while a save runs. */
export const selectedLanguage = signal<string>(lang.value);
export const selectedSpeedUnit = signal<SpeedUnit>("kmh");
export const languageFeedback = signal<Feedback | null>(null);
export const speedUnitFeedback = signal<Feedback | null>(null);

function normalizeSpeedUnit(value: string | null | undefined): SpeedUnit {
  return value === "mps" ? "mps" : "kmh";
}

function applySpeedUnit(value: string | null | undefined): void {
  speedUnit.value = normalizeSpeedUnit(value);
  selectedSpeedUnit.value = speedUnit.value;
}

async function applyLanguage(value: string): Promise<void> {
  await setLanguage(value);
  selectedLanguage.value = lang.value;
}

function saveFailedFeedback(
  label: string,
  activeValue: string,
  error: unknown,
): Feedback {
  return {
    body: t("settings.preference.save_failed_active", {
      label,
      value: activeValue,
    }),
    compact: true,
    detail: errorMessage(error, t("settings.save_failed")),
    tone: "error",
  };
}

export async function loadPreferences(): Promise<void> {
  const [language, unit] = await Promise.allSettled([
    getSettingsLanguage(),
    getSettingsSpeedUnit(),
  ]);
  if (language.status === "rejected") {
    uiLogger.warn("Failed to load persisted language", language.reason);
  } else if (language.value?.language) {
    await applyLanguage(language.value.language);
  }
  if (unit.status === "rejected") {
    uiLogger.warn("Failed to load persisted speed unit", unit.reason);
  } else if (unit.value?.speed_unit) {
    applySpeedUnit(unit.value.speed_unit);
  }
}

export async function saveLanguage(value: string): Promise<void> {
  const previous = lang.value;
  languageFeedback.value = null;
  selectedLanguage.value = normalizeLang(value);
  try {
    const saved = await setSettingsLanguage(selectedLanguage.value);
    await applyLanguage(saved?.language || selectedLanguage.value);
  } catch (error) {
    selectedLanguage.value = previous;
    languageFeedback.value = saveFailedFeedback(
      t("settings.language"),
      previous === "nl" ? "Nederlands" : "English",
      error,
    );
  }
}

export async function saveSpeedUnit(value: string): Promise<void> {
  const previous = speedUnit.value;
  speedUnitFeedback.value = null;
  selectedSpeedUnit.value = normalizeSpeedUnit(value);
  try {
    const saved = await setSettingsSpeedUnit(selectedSpeedUnit.value);
    applySpeedUnit(saved?.speed_unit || selectedSpeedUnit.value);
  } catch (error) {
    selectedSpeedUnit.value = previous;
    speedUnitFeedback.value = saveFailedFeedback(
      t("speed.unit"),
      t(speedUnitKey(previous)),
      error,
    );
  }
}

import { get as translate, normalizeLang } from "../i18n";
import { signal, useComputed, type ReadonlySignal } from "./ui_signals";

const currentLanguage = signal("en");

export function getUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): string {
  return translate(currentLanguage.value, key, vars) || fallback;
}

export function setUiLanguage(lang: string): void {
  const normalizedLanguage = normalizeLang(lang);
  if (normalizedLanguage === currentLanguage.value) {
    return;
  }
  currentLanguage.value = normalizedLanguage;
}

export function useUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): ReadonlySignal<string> {
  return useComputed(() => translate(currentLanguage.value, key, vars) || fallback);
}

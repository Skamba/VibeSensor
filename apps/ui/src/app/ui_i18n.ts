import { ensureCatalogLoaded, get as translate, normalizeLang } from "../i18n";
import { signal, useComputed, type ReadonlySignal } from "./ui_signals";

const currentLanguage = signal("en");

export async function setUiLanguage(lang: string): Promise<void> {
  const normalizedLanguage = normalizeLang(lang);
  await ensureCatalogLoaded(normalizedLanguage);
  if (normalizedLanguage === currentLanguage.value) {
    return;
  }
  currentLanguage.value = normalizedLanguage;
}

export function translateUiText(
  key: string,
  vars?: Record<string, unknown>,
): string {
  return translate(currentLanguage.value, key, vars);
}

export function getUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): string {
  return translateUiText(key, vars) || fallback;
}

export function useUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): ReadonlySignal<string> {
  return useComputed(() => translateUiText(key, vars) || fallback);
}

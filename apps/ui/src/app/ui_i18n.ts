import { useEffect, useState } from "preact/hooks";

import { get as translate, normalizeLang } from "../i18n";

type TranslationListener = () => void;

let currentLanguage = "en";
const listeners = new Set<TranslationListener>();

function notifyLanguageListeners(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function getUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): string {
  return translate(currentLanguage, key, vars) || fallback;
}

export function setUiLanguage(lang: string): void {
  const normalizedLanguage = normalizeLang(lang);
  if (normalizedLanguage === currentLanguage) {
    return;
  }
  currentLanguage = normalizedLanguage;
  notifyLanguageListeners();
}

export function useUiTranslation() {
  const [, setVersion] = useState(0);

  useEffect(() => {
    const listener = () => {
      setVersion((version) => version + 1);
    };
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return (
    key: string,
    fallback: string,
    vars?: Record<string, unknown>,
  ): string => getUiText(key, fallback, vars);
}

import { signal } from "@preact/signals";

import en from "./i18n/catalogs/en.json" with { type: "json" };
import { getDefaultNumberFormat } from "./number_format";

type Catalog = Record<string, string>;
export type Lang = "en" | "nl";

export type NumberVar = {
  number: number;
  options?: Intl.NumberFormatOptions;
};

const PLACEHOLDER_RE = /\{([a-zA-Z0-9_]+)\}/g;
const catalogs: Record<Lang, Catalog | null> = { en, nl: null };

/** The active UI language; reading it inside a render or computed subscribes. */
export const lang = signal<Lang>("en");

export function normalizeLang(value: string | null | undefined): Lang {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .startsWith("nl")
    ? "nl"
    : "en";
}

/** Loads the catalog (Dutch is a separate lazy chunk), then switches language. */
export async function setLanguage(value: string): Promise<void> {
  const next = normalizeLang(value);
  if (catalogs[next] === null) {
    catalogs[next] = (await import("./i18n/catalogs/nl.json")).default;
  }
  lang.value = next;
  globalThis.document?.documentElement.setAttribute("lang", next);
}

function formatVar(language: Lang, value: unknown): string {
  if (typeof value === "object" && value !== null && "number" in value) {
    const { number, options } = value as NumberVar;
    return Number.isFinite(number)
      ? new Intl.NumberFormat(language, options).format(number)
      : "--";
  }
  if (typeof value === "number") {
    return Number.isFinite(value)
      ? getDefaultNumberFormat(language).format(value)
      : "--";
  }
  return String(value);
}

/** Translates `key` in `language`, falling back to English, then the key. */
export function translate(
  language: Lang,
  key: string,
  vars?: Record<string, unknown>,
): string {
  const template =
    catalogs[language]?.[key] || en[key as keyof typeof en] || key;
  if (!vars) {
    return template;
  }
  return template.replace(PLACEHOLDER_RE, (match, name: string) =>
    Object.hasOwn(vars, name) ? formatVar(language, vars[name]) : match,
  );
}

/** Translates `key` in the active language. */
export function t(key: string, vars?: Record<string, unknown>): string {
  return translate(lang.value, key, vars);
}

/** The key's text in every loaded language (used to match free-text labels). */
export function translationsOf(key: string): string[] {
  return (Object.keys(catalogs) as Lang[]).map((language) =>
    translate(language, key),
  );
}

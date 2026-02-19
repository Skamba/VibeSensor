import enCatalog from "./i18n/catalogs/en.json";
import nlCatalog from "./i18n/catalogs/nl.json";

type Catalog = Record<string, string>;

export const supported = ["en", "nl"] as const;

const dict: Record<string, Catalog> = {
  en: enCatalog,
  nl: nlCatalog,
};

export function normalizeLang(value: string): string {
  const raw = String(value || "").trim().toLowerCase();
  if (raw.startsWith("nl")) return "nl";
  return "en";
}

function format(template: string, vars?: Record<string, unknown>): string {
  if (!vars || typeof vars !== "object") return template;
  return String(template).replace(/\{([a-zA-Z0-9_]+)\}/g, (_m, key) => {
    if (Object.prototype.hasOwnProperty.call(vars, key)) return String(vars[key]);
    return `{${key}}`;
  });
}

export function get(lang: string, key: string, vars?: Record<string, unknown>): string {
  const normalized = normalizeLang(lang);
  const fallback = dict.en?.[key] || key;
  const template = dict[normalized]?.[key] || fallback;
  return format(template, vars);
}

export function getForAllLangs(key: string): string[] {
  return supported.map((lang) => get(lang, key));
}

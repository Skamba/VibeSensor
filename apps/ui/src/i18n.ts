import enCatalog from "./i18n/catalogs/en.json";
import nlCatalog from "./i18n/catalogs/nl.json";

type Catalog = Record<string, string>;

export type NumberVar = {
  number: number;
  options?: Intl.NumberFormatOptions;
};

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

function isNumberVar(value: unknown): value is NumberVar {
  return typeof value === "object" && value != null && "number" in value;
}

function formatVar(lang: string, value: unknown): string {
  if (isNumberVar(value)) {
    if (!Number.isFinite(value.number)) return "--";
    return new Intl.NumberFormat(lang, value.options).format(value.number);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "--";
    return new Intl.NumberFormat(lang).format(value);
  }
  return String(value);
}

export function get(lang: string, key: string, vars?: Record<string, unknown>): string {
  const normalized = normalizeLang(lang);
  const fallback = dict.en?.[key] || key;
  const template = dict[normalized]?.[key] || fallback;
  if (!vars || typeof vars !== "object") return template;
  return String(template).replace(/\{([a-zA-Z0-9_]+)\}/g, (_m, placeholder) => {
    if (Object.prototype.hasOwnProperty.call(vars, placeholder)) {
      return formatVar(normalized, vars[placeholder]);
    }
    return `{${placeholder}}`;
  });
}

export function number(value: number, options?: Intl.NumberFormatOptions): NumberVar {
  return { number: value, options };
}

export function getForAllLangs(key: string): string[] {
  return supported.map((lang) => get(lang, key));
}

import enCatalog from "./i18n/catalogs/en.json";
import nlCatalog from "./i18n/catalogs/nl.json";

type Catalog = Record<string, string>;

export type NumberVar = {
  number: number;
  options?: Intl.NumberFormatOptions;
};

export const supported = ["en", "nl"] as const;

const _PLACEHOLDER_RE = /\{([a-zA-Z0-9_]+)\}/g;
const _numberFormatCache = new Map<string, Intl.NumberFormat>();

function _getDefaultNumberFormat(lang: string): Intl.NumberFormat {
  let fmt = _numberFormatCache.get(lang);
  if (!fmt) {
    fmt = new Intl.NumberFormat(lang);
    _numberFormatCache.set(lang, fmt);
  }
  return fmt;
}

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
    return _getDefaultNumberFormat(lang).format(value);
  }
  return String(value);
}

export function get(lang: string, key: string, vars?: Record<string, unknown>): string {
  const normalized = normalizeLang(lang);
  const fallback = dict.en?.[key] || key;
  const template = dict[normalized]?.[key] || fallback;
  if (!vars || typeof vars !== "object") return template;
  return String(template).replace(_PLACEHOLDER_RE, (_m, placeholder) => {
    if (Object.prototype.hasOwnProperty.call(vars, placeholder)) {
      return formatVar(normalized, vars[placeholder]);
    }
    return `{${placeholder}}`;
  });
}

export function getForAllLangs(key: string): string[] {
  return supported.map((lang) => get(lang, key));
}

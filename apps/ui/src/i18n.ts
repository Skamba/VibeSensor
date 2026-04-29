import enCatalog from "./i18n/catalogs/en.json" with { type: "json" };
import { getDefaultNumberFormat } from "./number_format";

type Catalog = Record<string, string>;
type CatalogModule = { default: Catalog };

export type NumberVar = {
  number: number;
  options?: Intl.NumberFormatOptions;
};

const supported = ["en", "nl"] as const;
type SupportedLanguage = (typeof supported)[number];

const _PLACEHOLDER_RE = /\{([a-zA-Z0-9_]+)\}/g;
const _catalogs: Partial<Record<SupportedLanguage, Catalog>> = {
  en: enCatalog,
};
const _catalogLoads = new Map<SupportedLanguage, Promise<void>>();
const _catalogLoaders: Record<SupportedLanguage, () => Promise<CatalogModule>> = {
  nl: () => import("./i18n/catalogs/nl"),
  en: async () => ({ default: enCatalog }),
};

export function normalizeLang(value: string): string {
  const raw = String(value || "").trim().toLowerCase();
  if (raw.startsWith("nl")) return "nl";
  return "en";
}

function normalizeSupportedLanguage(value: string): SupportedLanguage {
  return normalizeLang(value) as SupportedLanguage;
}

export async function ensureCatalogLoaded(lang: string): Promise<void> {
  const normalized = normalizeSupportedLanguage(lang);
  if (_catalogs[normalized]) {
    return;
  }
  const existingLoad = _catalogLoads.get(normalized);
  if (existingLoad) {
    await existingLoad;
    return;
  }
  const load = _catalogLoaders[normalized]().then((module) => {
    _catalogs[normalized] = module.default;
  });
  _catalogLoads.set(normalized, load);
  try {
    await load;
  } finally {
    _catalogLoads.delete(normalized);
  }
}

function getLoadedCatalog(lang: string): Catalog | undefined {
  return _catalogs[normalizeSupportedLanguage(lang)];
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
    return getDefaultNumberFormat(lang).format(value);
  }
  return String(value);
}

export function get(lang: string, key: string, vars?: Record<string, unknown>): string {
  const normalized = normalizeLang(lang);
  const fallback = getLoadedCatalog("en")?.[key] || key;
  const template = getLoadedCatalog(normalized)?.[key] || fallback;
  if (!vars || typeof vars !== "object") return template;
  return String(template).replace(_PLACEHOLDER_RE, (_m, placeholder) => {
    if (Object.hasOwn(vars, placeholder)) {
      return formatVar(normalized, vars[placeholder]);
    }
    return `{${placeholder}}`;
  });
}

export function getForAllLangs(key: string): string[] {
  return supported.map((lang) => getLoadedCatalog(lang)?.[key] || key);
}

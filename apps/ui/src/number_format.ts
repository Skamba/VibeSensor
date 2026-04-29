const defaultNumberFormatCache = new Map<string, Intl.NumberFormat>();

export function getDefaultNumberFormat(lang: string): Intl.NumberFormat {
  let fmt = defaultNumberFormatCache.get(lang);
  if (!fmt) {
    fmt = new Intl.NumberFormat(lang);
    defaultNumberFormatCache.set(lang, fmt);
  }
  return fmt;
}

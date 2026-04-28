export function fmt(n: number, digits = 2): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "--";
  return n.toFixed(digits);
}

function formatDateTime(date: Date, invalidText: string): string {
  if (Number.isNaN(date.getTime())) {
    return invalidText;
  }
  return date.toLocaleString();
}

export function fmtTs(iso: string): string {
  if (!iso) return "--";
  return formatDateTime(new Date(iso), iso);
}

export function formatEpochTimestamp(epoch: number | null | undefined): string {
  if (epoch === null || epoch === undefined || !Number.isFinite(epoch)) {
    return "—";
  }
  return formatDateTime(new Date(epoch * 1000), "—");
}

const _defaultNumberFormat = new Intl.NumberFormat();
const _localeFormatCache = new Map<string, Intl.NumberFormat>();

function formatInt(value: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return _defaultNumberFormat.format(Math.round(value));
}

/** Like formatInt but respects the given BCP 47 locale tag (e.g. "nl", "en"). */
export function formatIntLocale(value: number, lang: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  let fmt = _localeFormatCache.get(lang);
  if (!fmt) {
    fmt = new Intl.NumberFormat(lang);
    _localeFormatCache.set(lang, fmt);
  }
  return fmt.format(Math.round(value));
}

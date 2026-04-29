import { getDefaultNumberFormat } from "./number_format";

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

/** Like formatInt but respects the given BCP 47 locale tag (e.g. "nl", "en"). */
export function formatIntLocale(value: number, lang: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return getDefaultNumberFormat(lang).format(Math.round(value));
}

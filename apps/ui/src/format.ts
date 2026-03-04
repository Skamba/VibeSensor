export function fmt(n: number, digits = 2): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "--";
  return n.toFixed(digits);
}

export function fmtTs(iso: string): string {
  if (!iso) return "--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

const _defaultNumberFormat = new Intl.NumberFormat();

export function formatInt(value: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return _defaultNumberFormat.format(Math.round(value));
}

const _HTML_ESCAPE_RE = /[&<>"']/g;
const _HTML_ESCAPE_MAP: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value: unknown): string {
  return String(value).replace(_HTML_ESCAPE_RE, (ch) => _HTML_ESCAPE_MAP[ch]);
}

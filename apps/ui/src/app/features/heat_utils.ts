/** Normalize a value to 0..1 within a [min, max] range. */
export function normalizeUnit(value: number, min: number, max: number): number {
  if (!(typeof value === "number") || !Number.isFinite(value)) return 0;
  if (!(typeof min === "number") || !(typeof max === "number")) return 0;
  // When only one data point exists (min === max), use mid-range so the
  // heatmap dot reflects actual severity instead of always showing "cold".
  if (max <= min) return min > 0 ? 0.5 : 0;
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

/** Map a 0..1 norm to a blue→red heatmap HSL color. */
export function heatColor(norm: number): string {
  const hue = Math.round(212 - (norm * 190));
  return `hsl(${hue} 76% 48%)`;
}

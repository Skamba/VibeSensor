export type TireSpec = {
  widthMm: number;
  aspect: number;
  rimIn: number;
};

export type VehicleSettings = {
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  speed_uncertainty_pct: number;
  tire_diameter_uncertainty_pct: number;
  final_drive_uncertainty_pct: number;
  gear_uncertainty_pct: number;
  min_abs_band_hz: number;
  max_band_half_width_pct: number;
};

export function parseTireSpec(raw: unknown): TireSpec | null {
  if (!raw || typeof raw !== "object") return null;
  const typed = raw as { widthMm?: unknown; aspect?: unknown; rimIn?: unknown };
  const widthMm = Number(typed.widthMm);
  const aspect = Number(typed.aspect);
  const rimIn = Number(typed.rimIn);
  if (!(widthMm > 0 && aspect >= 0 && rimIn > 0)) return null;
  return { widthMm, aspect, rimIn };
}

export function tireDiameterMeters(spec: TireSpec): number {
  const sidewallMm = spec.widthMm * (spec.aspect / 100);
  const diameterMm = spec.rimIn * 25.4 + sidewallMm * 2;
  return diameterMm / 1000;
}

export function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function combinedRelativeUncertainty(...parts: number[]): number {
  let sumSq = 0;
  for (const p of parts) {
    if (typeof p === "number" && p > 0) sumSq += p * p;
  }
  return Math.sqrt(sumSq);
}

export function toleranceForOrder(
  baseBandwidthPct: number,
  orderHz: number,
  uncertaintyPct: number,
  minAbsBandHz: number,
  maxBandHalfWidthPct: number,
): number {
  const baseHalfRel = Math.max(0, Number(baseBandwidthPct) || 0) / 200.0;
  const absFloor = Math.max(0, minAbsBandHz || 0) / Math.max(1, orderHz);
  const maxHalfRel = Math.max(0.005, (maxBandHalfWidthPct || 0) / 100.0);
  const combined = Math.sqrt(baseHalfRel * baseHalfRel + uncertaintyPct * uncertaintyPct);
  return Math.min(maxHalfRel, Math.max(combined, absFloor));
}

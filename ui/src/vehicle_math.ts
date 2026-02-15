import { bandToleranceModelVersion, treadWearModel } from "./constants";

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

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function rssPct(...parts: number[]): number {
  let sumSq = 0;
  for (const p of parts) {
    if (typeof p === "number" && p > 0) sumSq += p * p;
  }
  return Math.sqrt(sumSq);
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

export function buildRecommendedBandDefaults(
  vehicleSettings: Pick<VehicleSettings, "tire_width_mm" | "tire_aspect_pct" | "rim_in">,
): Record<string, number> {
  const tire = parseTireSpec({
    widthMm: vehicleSettings.tire_width_mm,
    aspect: vehicleSettings.tire_aspect_pct,
    rimIn: vehicleSettings.rim_in,
  });
  const diameterMm = tire ? tireDiameterMeters(tire) * 1000 : 700;
  const treadLossMm = Math.max(0, treadWearModel.new_tread_mm - treadWearModel.worn_tread_mm);
  const wearSpanPct = (2 * treadLossMm * 100) / Math.max(100, diameterMm);
  const tireUncertaintyPct = clamp((wearSpanPct / 2) + treadWearModel.safety_margin_pct, 0.6, 2.5);
  const speedUncertaintyPct = 0.6;
  const finalDriveUncertaintyPct = 0.2;
  const gearUncertaintyPct = 0.5;

  const wheelUncPct = rssPct(speedUncertaintyPct, tireUncertaintyPct);
  const driveshaftUncPct = rssPct(wheelUncPct, finalDriveUncertaintyPct);
  const engineUncPct = rssPct(driveshaftUncPct, gearUncertaintyPct);

  const wheelBandwidthPct = clamp(2 * ((wheelUncPct * 1.2) + 1.0), 4.0, 12.0);
  const driveshaftBandwidthPct = clamp(2 * ((driveshaftUncPct * 1.2) + 0.9), 4.0, 11.0);
  const engineBandwidthPct = clamp(2 * ((engineUncPct * 1.2) + 1.0), 4.5, 12.0);

  return {
    wheel_bandwidth_pct: round1(wheelBandwidthPct),
    driveshaft_bandwidth_pct: round1(driveshaftBandwidthPct),
    engine_bandwidth_pct: round1(engineBandwidthPct),
    speed_uncertainty_pct: speedUncertaintyPct,
    tire_diameter_uncertainty_pct: round1(tireUncertaintyPct),
    final_drive_uncertainty_pct: finalDriveUncertaintyPct,
    gear_uncertainty_pct: gearUncertaintyPct,
    min_abs_band_hz: 0.4,
    max_band_half_width_pct: 8.0,
    band_tolerance_model_version: bandToleranceModelVersion,
  };
}

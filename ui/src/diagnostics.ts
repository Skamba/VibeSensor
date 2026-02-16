import { severityBands, sourceColumns } from "./constants";

export function createEmptyMatrix(): Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>> {
  const matrix: Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>> = {};
  for (const src of sourceColumns) {
    matrix[src.key] = {};
    for (const band of severityBands) {
      matrix[src.key][band.key] = { count: 0, seconds: 0, contributors: {} };
    }
  }
  return matrix;
}

export function sourceKeysFromClassKey(classKey: string): string[] {
  if (classKey === "shaft_eng1") return ["driveshaft", "engine"];
  if (classKey === "eng1" || classKey === "eng2") return ["engine"];
  if (classKey === "shaft1") return ["driveshaft"];
  if (classKey === "wheel1" || classKey === "wheel2") return ["wheel"];
  return ["other"];
}

export function relativeDbAboveFloor(amplitude: number, floorAmplitude: number): number {
  const peak = Math.max(0, amplitude);
  const floor = Math.max(0, floorAmplitude);
  const eps = Math.max(1e-9, floor * 0.05);
  return 20 * Math.log10((peak + eps) / (floor + eps));
}

export function severityFromPeak(
  peakAmp: number,
  floorAmp: number,
  sensorCount: number,
): { key: string; labelKey: string; db: number } | null {
  const db = relativeDbAboveFloor(peakAmp, floorAmp);
  const adjustedDb = sensorCount >= 2 ? db + 3 : db;
  for (const band of severityBands) {
    if (adjustedDb >= band.minDb && adjustedDb < band.maxDb && peakAmp >= band.minAmp) {
      return { key: band.key, labelKey: band.labelKey, db: adjustedDb };
    }
  }
  return null;
}

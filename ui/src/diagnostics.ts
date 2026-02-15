import { severityBands, sourceColumns } from "./constants";

export function createEmptyMatrix(): Record<string, Record<string, { count: number; contributors: Record<string, number> }>> {
  const matrix: Record<string, Record<string, { count: number; contributors: Record<string, number> }>> = {};
  for (const src of sourceColumns) {
    matrix[src.key] = {};
    for (const band of severityBands) {
      matrix[src.key][band.key] = { count: 0, contributors: {} };
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
  return 20 * Math.log10((Math.max(0, amplitude) + 1) / (Math.max(0, floorAmplitude) + 1));
}

export function severityFromPeak(
  peakAmp: number,
  floorAmp: number,
  sensorCount: number,
): { key: string; labelKey: string; db: number } | null {
  const db = relativeDbAboveFloor(peakAmp, floorAmp);
  // Multi-sensor synchronous detections are stronger indicators than single-sensor events.
  const adjustedDb = sensorCount >= 2 ? db + 2 : db;
  for (const band of severityBands) {
    if (adjustedDb >= band.minDb && adjustedDb < band.maxDb) {
      return { key: band.key, labelKey: band.labelKey, db: adjustedDb };
    }
  }
  return null;
}

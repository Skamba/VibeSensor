import { defaultStrengthBands, sourceColumns } from "./constants";

export type StrengthBand = {
  key: string;
  min_db: number;
  min_amp: number;
  max_db?: number;
  labelKey?: string;
};

export function normalizeStrengthBands(input: unknown): StrengthBand[] {
  const parsed = Array.isArray(input)
    ? input
        .map((band) => {
          if (!band || typeof band !== "object") return null;
          const key = String((band as any).key || "").toLowerCase();
          const minDb = Number((band as any).min_db);
          const minAmp = Number((band as any).min_amp);
          if (!key || !Number.isFinite(minDb) || !Number.isFinite(minAmp)) return null;
          return { key, min_db: minDb, min_amp: minAmp } as StrengthBand;
        })
        .filter((band): band is StrengthBand => band !== null)
    : [];
  const bands = parsed.length ? parsed : defaultStrengthBands;
  const ascending = [...bands].sort((a, b) => a.min_db - b.min_db);
  return ascending.map((band, idx) => ({
    ...band,
    max_db: idx + 1 < ascending.length ? ascending[idx + 1].min_db : Number.POSITIVE_INFINITY,
    labelKey: `matrix.severity.${band.key}`,
  }));
}

export function createEmptyMatrix(
  strengthBands: StrengthBand[] = normalizeStrengthBands(defaultStrengthBands),
): Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>> {
  const matrix: Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>> = {};
  const ordered = [...strengthBands].sort((a, b) => b.min_db - a.min_db);
  for (const src of sourceColumns) {
    matrix[src.key] = {};
    for (const band of ordered) {
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

export function severityFromPeak(
  _peakAmp: number,
  _floorAmp: number,
  _sensorCount: number,
  _strengthBands: StrengthBand[],
): { key: string; labelKey: string; db: number } | null {
  throw new Error("Client-side strength bucket derivation is disabled; use server-provided severity_key");
}

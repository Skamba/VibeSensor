import { sourceColumns } from "./constants";

export type StrengthBand = {
  key: string;
  min_db: number;
  max_db?: number;
  labelKey?: string;
};

export function normalizeStrengthBands(input: unknown): StrengthBand[] {
  const parsed = Array.isArray(input)
    ? input
        .map((band) => {
          if (!band || typeof band !== "object") return null;
          const rec = band as Record<string, unknown>;
          const key = String(rec.key || "").toLowerCase();
          const minDb = Number(rec.min_db);
          if (!key || !Number.isFinite(minDb)) return null;
          return { key, min_db: minDb } as StrengthBand;
        })
        .filter((band): band is StrengthBand => band !== null)
    : [];
  const ascending = [...parsed].sort((a, b) => a.min_db - b.min_db);
  return ascending.map((band, idx) => ({
    ...band,
    max_db: idx + 1 < ascending.length ? ascending[idx + 1].min_db : Number.POSITIVE_INFINITY,
    labelKey: `matrix.severity.${band.key}`,
  }));
}

export function createEmptyMatrix(
  strengthBands: StrengthBand[] = [],
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

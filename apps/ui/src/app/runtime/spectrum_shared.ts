export type SpectrumNumericSeries = readonly number[] | Float64Array;

export interface SpectrumSeriesEntry {
  id: string;
  label: string;
  color: string;
  values: SpectrumNumericSeries;
}

export interface SpectrumFocusMarker {
  color: string;
  freq: number;
  value: number;
}

const FREQ_MATCH_EPSILON = 1e-6;

export function closestFrequencyIndex(
  freqAxis: SpectrumNumericSeries,
  targetHz: number,
): number | null {
  if (!freqAxis.length || !Number.isFinite(targetHz)) {
    return null;
  }
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < freqAxis.length; index += 1) {
    const distance = Math.abs(freqAxis[index] - targetHz);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  }
  return bestIndex;
}

export function freqGridsMatch(
  left: SpectrumNumericSeries,
  right: SpectrumNumericSeries,
  len: number,
): boolean {
  for (let index = 0; index < len; index += 1) {
    if (Math.abs(left[index] - right[index]) > FREQ_MATCH_EPSILON) {
      return false;
    }
  }
  return true;
}

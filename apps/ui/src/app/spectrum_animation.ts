export interface SpectrumHeavyFrame {
  seriesIds: string[];
  freq: number[];
  values: number[][];
  /** Cached fingerprint for fast frequency-grid equality checks. */
  _freqFingerprint?: string;
}

const FREQ_EPSILON = 1e-6;

/** Compute a lightweight fingerprint (length + sampled values) for a freq array. */
function freqFingerprint(freq: number[]): string {
  const n = freq.length;
  if (n === 0) return "0";
  // Sample first, last, and up to 4 evenly-spaced interior points.
  const indices = [0, n - 1];
  for (let k = 1; k <= 4 && k * (n - 1) / 5 < n; k++) {
    indices.push(Math.round(k * (n - 1) / 5));
  }
  const parts = [String(n)];
  for (const idx of indices) {
    parts.push(freq[idx].toFixed(4));
  }
  return parts.join(",");
}

/** Get or compute the freq fingerprint for a frame. */
function getFreqFingerprint(frame: SpectrumHeavyFrame): string {
  if (frame._freqFingerprint === undefined) {
    frame._freqFingerprint = freqFingerprint(frame.freq);
  }
  return frame._freqFingerprint;
}

export function areHeavyFramesCompatible(previous: SpectrumHeavyFrame | null, next: SpectrumHeavyFrame): boolean {
  if (!previous) return false;
  if (previous.seriesIds.length !== next.seriesIds.length) return false;
  if (previous.values.length !== next.values.length) return false;
  for (let i = 0; i < previous.seriesIds.length; i++) {
    if (previous.seriesIds[i] !== next.seriesIds[i]) return false;
  }
  // Fast path: fingerprint mismatch means definitely incompatible.
  if (getFreqFingerprint(previous) !== getFreqFingerprint(next)) return false;
  // Only do the full element-wise check if fingerprints match but we haven't
  // verified the arrays are identical references.
  if (previous.freq !== next.freq) {
    if (previous.freq.length !== next.freq.length) return false;
    for (let i = 0; i < previous.freq.length; i++) {
      if (Math.abs(previous.freq[i] - next.freq[i]) > FREQ_EPSILON) return false;
    }
  }
  for (let i = 0; i < previous.values.length; i++) {
    if (previous.values[i].length !== next.values[i].length || previous.values[i].length !== previous.freq.length) return false;
  }
  return true;
}

export function interpolateHeavyFrame(previous: SpectrumHeavyFrame, next: SpectrumHeavyFrame, alpha: number): SpectrumHeavyFrame {
  const t = Math.min(1, Math.max(0, alpha));
  const outValues: number[][] = new Array(next.values.length);
  for (let s = 0; s < next.values.length; s++) {
    const series = next.values[s];
    const prevSeries = previous.values[s];
    const out = new Array<number>(series.length);
    for (let p = 0; p < series.length; p++) {
      out[p] = prevSeries[p] + (series[p] - prevSeries[p]) * t;
    }
    outValues[s] = out;
  }
  return {
    seriesIds: next.seriesIds,
    freq: next.freq,
    values: outValues,
    _freqFingerprint: next._freqFingerprint,
  };
}

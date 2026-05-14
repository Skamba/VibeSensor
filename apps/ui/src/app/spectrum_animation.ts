import { computed, type ReadonlySignal } from "./ui_signals";
import type { SpectrumNumericSeries } from "./runtime/spectrum_shared";

export interface SpectrumHeavyFrame {
  seriesIds: string[];
  freq: SpectrumNumericSeries;
  values: SpectrumNumericSeries[];
  /** Cached fingerprint for fast frequency-grid equality checks. */
  _freqFingerprint?: string;
}

const FREQ_EPSILON = 1e-6;
const MAX_INTERIOR_FINGERPRINT_SAMPLES = 4;
const FINGERPRINT_SAMPLE_SEGMENTS = MAX_INTERIOR_FINGERPRINT_SAMPLES + 1;
const MIN_TWEEN_DURATION_MS = 60;
const FAST_FRAME_TWEEN_FRACTION = 0.75;

/** Compute a lightweight fingerprint (length + sampled values) for a freq array. */
function freqFingerprint(freq: SpectrumNumericSeries): string {
  const n = freq.length;
  if (n === 0) return "0";
  // Sample first, last, and up to 4 evenly-spaced interior points.
  const indices = [0, n - 1];
  for (
    let k = 1;
    k <= MAX_INTERIOR_FINGERPRINT_SAMPLES &&
    (k * (n - 1)) / FINGERPRINT_SAMPLE_SEGMENTS < n;
    k++
  ) {
    indices.push(Math.round((k * (n - 1)) / FINGERPRINT_SAMPLE_SEGMENTS));
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

function areHeavyFramesCompatible(
  previous: SpectrumHeavyFrame | null,
  next: SpectrumHeavyFrame,
): boolean {
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
      if (Math.abs(previous.freq[i] - next.freq[i]) > FREQ_EPSILON)
        return false;
    }
  }
  for (let i = 0; i < previous.values.length; i++) {
    if (
      previous.values[i].length !== next.values[i].length ||
      previous.values[i].length !== previous.freq.length
    )
      return false;
  }
  return true;
}

function interpolateHeavyFrame(
  previous: SpectrumHeavyFrame,
  next: SpectrumHeavyFrame,
  alpha: number,
): SpectrumHeavyFrame {
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

export function resolveSpectrumTweenDurationMs(
  baseDurationMs: number,
  frameIntervalMs: number | null,
): number {
  if (!Number.isFinite(baseDurationMs) || baseDurationMs <= 0) {
    return 0;
  }
  if (frameIntervalMs === null) {
    return baseDurationMs;
  }
  if (!Number.isFinite(frameIntervalMs) || frameIntervalMs <= 0) {
    return 0;
  }
  if (frameIntervalMs >= baseDurationMs) {
    return baseDurationMs;
  }
  const shortenedDurationMs = Math.min(
    baseDurationMs,
    frameIntervalMs * FAST_FRAME_TWEEN_FRACTION,
  );
  return shortenedDurationMs >= MIN_TWEEN_DURATION_MS ? shortenedDurationMs : 0;
}

export interface SpectrumTweenDerivedState {
  canTween: ReadonlySignal<boolean>;
  frame: ReadonlySignal<SpectrumHeavyFrame | null>;
}

export function createSpectrumTweenDerivedState(
  previousFrame: ReadonlySignal<SpectrumHeavyFrame | null>,
  nextFrame: ReadonlySignal<SpectrumHeavyFrame | null>,
  alpha: ReadonlySignal<number>,
): SpectrumTweenDerivedState {
  const canTween = computed(() => {
    const next = nextFrame.value;
    return next !== null && areHeavyFramesCompatible(previousFrame.value, next);
  });
  const frame = computed(() => {
    const next = nextFrame.value;
    if (!next) {
      return null;
    }
    const previous = previousFrame.value;
    if (!previous || !canTween.value) {
      return next;
    }
    return interpolateHeavyFrame(previous, next, alpha.value);
  });

  return {
    canTween,
    frame,
  };
}

import {
  SPECTRUM_DB_MAX,
  SPECTRUM_DB_MIN,
  SPECTRUM_DB_REFERENCE_AMP_G,
  SPECTRUM_MIN_RENDER_AMP_G,
} from "./config";

const SPECTRUM_LOG10_REF = Math.log10(SPECTRUM_DB_REFERENCE_AMP_G);

export function convertSpectrumAmplitudesToDbInPlace(values: number[]): void {
  for (let i = 0; i < values.length; i += 1) {
    const amplitude = values[i];
    const safe = Number.isFinite(amplitude) && amplitude > 0
      ? Math.max(amplitude, SPECTRUM_MIN_RENDER_AMP_G)
      : SPECTRUM_MIN_RENDER_AMP_G;
    const db = 20 * (Math.log10(safe) - SPECTRUM_LOG10_REF);
    values[i] = Math.max(SPECTRUM_DB_MIN, Math.min(SPECTRUM_DB_MAX, db));
  }
}

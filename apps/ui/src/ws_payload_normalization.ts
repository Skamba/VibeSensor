import type { StrengthMetricPeak, StrengthMetricsPayload } from "./contracts/ws_payload_types";

const EMPTY_STRENGTH_METRICS: StrengthMetricsPayload = {
  vibration_strength_db: 0,
  peak_amp_g: 0,
  noise_floor_amp_g: 0,
  strength_bucket: null,
  top_peaks: [],
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function normalizeStrengthMetricPeak(value: unknown): StrengthMetricPeak | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const { hz, amp, vibration_strength_db, strength_bucket } = value as Record<string, unknown>;
  if (!isFiniteNumber(hz) || !isFiniteNumber(amp) || !isFiniteNumber(vibration_strength_db)) {
    return null;
  }
  return {
    hz,
    amp,
    vibration_strength_db,
    strength_bucket: typeof strength_bucket === "string" || strength_bucket === null
      ? strength_bucket
      : null,
  };
}

function normalizeStrengthMetrics(value: unknown): StrengthMetricsPayload | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const {
    vibration_strength_db,
    peak_amp_g,
    noise_floor_amp_g,
    strength_bucket,
    top_peaks,
  } = value as Record<string, unknown>;
  return {
    vibration_strength_db: isFiniteNumber(vibration_strength_db)
      ? vibration_strength_db
      : EMPTY_STRENGTH_METRICS.vibration_strength_db,
    peak_amp_g: isFiniteNumber(peak_amp_g) ? peak_amp_g : EMPTY_STRENGTH_METRICS.peak_amp_g,
    noise_floor_amp_g: isFiniteNumber(noise_floor_amp_g)
      ? noise_floor_amp_g
      : EMPTY_STRENGTH_METRICS.noise_floor_amp_g,
    strength_bucket: typeof strength_bucket === "string" || strength_bucket === null
      ? strength_bucket
      : EMPTY_STRENGTH_METRICS.strength_bucket,
    top_peaks: Array.isArray(top_peaks)
      ? top_peaks
          .map((peak) => normalizeStrengthMetricPeak(peak))
          .filter((peak): peak is StrengthMetricPeak => peak !== null)
      : EMPTY_STRENGTH_METRICS.top_peaks,
  };
}

function normalizeSpectrumSeries(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { value };
  }

  const normalizedSpectrum = { ...(value as Record<string, unknown>) };
  if (Array.isArray(normalizedSpectrum.freq) && !normalizedSpectrum.freq.every(isFiniteNumber)) {
    return { value };
  }
  if (
    Array.isArray(normalizedSpectrum.combined_spectrum_amp_g) &&
    !normalizedSpectrum.combined_spectrum_amp_g.every(isFiniteNumber)
  ) {
    return { value };
  }

  const strengthMetrics = normalizeStrengthMetrics(normalizedSpectrum.strength_metrics);
  if (strengthMetrics) {
    normalizedSpectrum.strength_metrics = strengthMetrics;
  } else {
    delete normalizedSpectrum.strength_metrics;
  }
  return normalizedSpectrum;
}

export function normalizePayloadForValidation(payload: Record<string, unknown>): Record<string, unknown> {
  const spectra = payload.spectra;
  if (spectra === null || typeof spectra !== "object" || Array.isArray(spectra)) {
    return payload;
  }

  const normalizedSpectra = { ...(spectra as Record<string, unknown>) };
  const clients = normalizedSpectra.clients;
  if (clients === null || typeof clients !== "object" || Array.isArray(clients)) {
    return {
      ...payload,
      spectra: normalizedSpectra,
    };
  }

  if (Array.isArray(normalizedSpectra.freq) && !normalizedSpectra.freq.every(isFiniteNumber)) {
    delete normalizedSpectra.freq;
  }

  const normalizedClients: Record<string, Record<string, unknown>> = {};
  for (const [clientId, spectrum] of Object.entries(clients)) {
    normalizedClients[clientId] = normalizeSpectrumSeries(spectrum);
  }

  return {
    ...payload,
    spectra: {
      ...normalizedSpectra,
      clients: normalizedClients,
    },
  };
}

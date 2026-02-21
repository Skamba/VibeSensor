import type { StrengthBand } from "./diagnostics";

export type AdaptedSpectrum = {
  freq: number[];
  combined: number[];
  strength_metrics: Record<string, unknown>;
};

type ClientInfo = {
  client_id: string;
  name: string;
  last_seen_ms: number;
  sample_rate_hz: number;
  location_code: string;
  firmware_version: string;
  [key: string]: unknown;
};

type DiagnosticEvent = {
  source: string;
  severity: string;
  client_id: string;
  peak_hz: number;
  strength_db: number;
  ts_ms: number;
  [key: string]: unknown;
};

type DiagnosticLevel = {
  current_db: number;
  band_key: string;
  [key: string]: unknown;
};

type DiagnosticLevels = {
  by_source: Record<string, DiagnosticLevel>;
  by_sensor: Record<string, DiagnosticLevel>;
};

type MatrixCell = { count: number; seconds: number; contributors: Record<string, number> };

export type AdaptedPayload = {
  clients: ClientInfo[];
  speed_mps: number | null;
  diagnostics: {
    strength_bands: StrengthBand[];
    matrix: Record<string, Record<string, MatrixCell>> | null;
    events: DiagnosticEvent[];
    levels: DiagnosticLevels;
  };
  spectra: {
    clients: Record<string, AdaptedSpectrum>;
  } | null;
};

function asNumberArray(value: unknown): number[] {
  return Array.isArray(value) ? value.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [];
}

export function adaptServerPayload(payload: Record<string, unknown>): AdaptedPayload {
  if (!payload || typeof payload !== "object") {
    throw new Error("Missing websocket payload.");
  }
  if (!payload.diagnostics || typeof payload.diagnostics !== "object") {
    throw new Error("Missing diagnostics payload from server.");
  }
  const diagnostics = payload.diagnostics as Record<string, unknown>;
  const strengthBands = Array.isArray(diagnostics.strength_bands)
    ? (diagnostics.strength_bands as StrengthBand[])
    : [];
  if (!strengthBands.length) {
    // No strength bands yet — return payload with empty bands.
  }

  const adapted: AdaptedPayload = {
    clients: Array.isArray(payload.clients) ? (payload.clients as ClientInfo[]) : [],
    speed_mps: typeof payload.speed_mps === "number" ? payload.speed_mps : null,
    diagnostics: {
      strength_bands: strengthBands,
      matrix:
        diagnostics.matrix && typeof diagnostics.matrix === "object"
          ? (diagnostics.matrix as AdaptedPayload["diagnostics"]["matrix"])
          : null,
      events: Array.isArray(diagnostics.events) ? (diagnostics.events as DiagnosticEvent[]) : [],
      levels:
        diagnostics.levels && typeof diagnostics.levels === "object"
          ? (diagnostics.levels as DiagnosticLevels)
          : { by_source: {}, by_sensor: {} },
    },
    spectra: null,
  };

  if (payload.spectra && typeof payload.spectra === "object") {
    const spectraObj = payload.spectra as Record<string, unknown>;
    const clients = spectraObj.clients;
    if (!clients || typeof clients !== "object") {
      throw new Error("Missing spectra.clients payload from server.");
    }
    adapted.spectra = { clients: {} };
    for (const [clientId, spectrum] of Object.entries(clients as Record<string, unknown>)) {
      if (!spectrum || typeof spectrum !== "object") continue;
      const specObj = spectrum as Record<string, unknown>;
      const freq = asNumberArray(specObj.freq);
      const combined = asNumberArray(specObj.combined_spectrum_amp_g);
      const strengthMetrics = specObj.strength_metrics;
      if (!freq.length || !combined.length || !strengthMetrics || typeof strengthMetrics !== "object") {
        continue;  // skip this client's incomplete spectrum
      }
      adapted.spectra.clients[clientId] = {
        freq,
        combined,
        strength_metrics: strengthMetrics as Record<string, unknown>,
      };
    }
  }

  return adapted;
}

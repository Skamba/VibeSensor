import type { StrengthBand } from "./diagnostics";

export type AdaptedSpectrum = {
  freq: number[];
  combined: number[];
  combinedDbAboveFloor: number[];
  strength_metrics: Record<string, unknown>;
};

export type ClientInfo = {
  client_id: string;
  name: string;
  last_seen_ms: number;
  sample_rate_hz: number;
  location_code: string;
  firmware_version: string;
  [key: string]: unknown;
};

export type DiagnosticEvent = {
  source: string;
  severity: string;
  client_id: string;
  peak_hz: number;
  strength_db: number;
  ts_ms: number;
  [key: string]: unknown;
};

export type DiagnosticLevel = {
  current_db: number;
  band_key: string;
  [key: string]: unknown;
};

export type MatrixCell = { count: number; seconds: number; contributors: Record<string, number> };

export type AdaptedPayload = {
  clients: ClientInfo[];
  speed_mps: number | null;
  diagnostics: {
    strength_bands: StrengthBand[];
    matrix: Record<string, Record<string, MatrixCell>> | null;
    events: DiagnosticEvent[];
    levels: Record<string, DiagnosticLevel>;
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
    throw new Error("Missing diagnostics.strength_bands payload from server.");
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
          ? (diagnostics.levels as Record<string, DiagnosticLevel>)
          : {},
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
      const combinedDbRaw = asNumberArray(specObj.combined_spectrum_db_above_floor);
      const combinedDbAboveFloor = combinedDbRaw.length === combined.length ? combinedDbRaw : [];
      if (!freq.length || !combined.length || !strengthMetrics || typeof strengthMetrics !== "object") {
        throw new Error(
          `Missing spectra.combined_spectrum_amp_g or strength_metrics for client ${clientId}.`,
        );
      }
      adapted.spectra.clients[clientId] = {
        freq,
        combined,
        combinedDbAboveFloor,
        strength_metrics: strengthMetrics as Record<string, unknown>,
      };
    }
  }

  return adapted;
}

import type { StrengthBand } from "./diagnostics";

export type AdaptedSpectrum = {
  freq: number[];
  combined: number[];
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
  strength_db: number;
  bucket_key: string;
  sensor_label?: string;
  sensor_location?: string;
  class_key?: string;
  peak_hz?: number;
  [key: string]: unknown;
};

export type DiagnosticLevels = {
  by_source: Record<string, DiagnosticLevel>;
  by_sensor: Record<string, DiagnosticLevel>;
  by_location: Record<string, DiagnosticLevel>;
};

export type MatrixCell = { count: number; seconds: number; contributors: Record<string, number> };

export type RotationalSpeedValue = {
  rpm: number | null;
  mode: string | null;
  reason: string | null;
};

export type RotationalSpeeds = {
  basis_speed_source: string | null;
  wheel: RotationalSpeedValue;
  driveshaft: RotationalSpeedValue;
  engine: RotationalSpeedValue;
};

export type AdaptedPayload = {
  clients: ClientInfo[];
  speed_mps: number | null;
  rotational_speeds: RotationalSpeeds | null;
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

function adaptRotationalSpeedValue(value: unknown): RotationalSpeedValue {
  if (!value || typeof value !== "object") {
    return { rpm: null, mode: null, reason: null };
  }
  const obj = value as Record<string, unknown>;
  return {
    rpm: typeof obj.rpm === "number" && Number.isFinite(obj.rpm) ? obj.rpm : null,
    mode: typeof obj.mode === "string" ? obj.mode : null,
    reason: typeof obj.reason === "string" ? obj.reason : null,
  };
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
    rotational_speeds: null,
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
          : { by_source: {}, by_sensor: {}, by_location: {} },
    },
    spectra: null,
  };

  if (payload.rotational_speeds && typeof payload.rotational_speeds === "object") {
    const rotational = payload.rotational_speeds as Record<string, unknown>;
    adapted.rotational_speeds = {
      basis_speed_source: typeof rotational.basis_speed_source === "string" ? rotational.basis_speed_source : null,
      wheel: adaptRotationalSpeedValue(rotational.wheel),
      driveshaft: adaptRotationalSpeedValue(rotational.driveshaft),
      engine: adaptRotationalSpeedValue(rotational.engine),
    };
  }

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

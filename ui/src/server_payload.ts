import type { StrengthBand } from "./diagnostics";

export type AdaptedSpectrum = {
  freq: number[];
  combined: number[];
  strength_metrics: Record<string, unknown>;
};

export type AdaptedPayload = {
  clients: any[];
  speed_mps: number | null;
  diagnostics: {
    strength_bands: StrengthBand[];
    matrix: Record<string, Record<string, { count: number; seconds: number; contributors: Record<string, number> }>> | null;
    events: any[];
    levels: Record<string, any>;
  };
  spectra: {
    clients: Record<string, AdaptedSpectrum>;
  } | null;
};

function asNumberArray(value: unknown): number[] {
  return Array.isArray(value) ? value.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [];
}

export function adaptServerPayload(payload: any): AdaptedPayload {
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
    clients: Array.isArray(payload.clients) ? payload.clients : [],
    speed_mps: typeof payload.speed_mps === "number" ? payload.speed_mps : null,
    diagnostics: {
      strength_bands: strengthBands,
      matrix:
        diagnostics.matrix && typeof diagnostics.matrix === "object"
          ? (diagnostics.matrix as AdaptedPayload["diagnostics"]["matrix"])
          : null,
      events: Array.isArray(diagnostics.events) ? diagnostics.events : [],
      levels:
        diagnostics.levels && typeof diagnostics.levels === "object"
          ? (diagnostics.levels as Record<string, any>)
          : {},
    },
    spectra: null,
  };

  if (payload.spectra && typeof payload.spectra === "object") {
    const clients = (payload.spectra as any).clients;
    if (!clients || typeof clients !== "object") {
      throw new Error("Missing spectra.clients payload from server.");
    }
    adapted.spectra = { clients: {} };
    for (const [clientId, spectrum] of Object.entries(clients as Record<string, unknown>)) {
      if (!spectrum || typeof spectrum !== "object") continue;
      const freq = asNumberArray((spectrum as any).freq);
      const combined = asNumberArray((spectrum as any).combined_spectrum_amp_g);
      const strengthMetrics = (spectrum as any).strength_metrics;
      if (!freq.length || !combined.length || !strengthMetrics || typeof strengthMetrics !== "object") {
        throw new Error(
          `Missing spectra.combined_spectrum_amp_g or strength_metrics for client ${clientId}.`,
        );
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

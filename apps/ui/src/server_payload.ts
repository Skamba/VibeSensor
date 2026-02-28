import type { StrengthBand } from "./diagnostics";
import { EXPECTED_SCHEMA_VERSION } from "./contracts/ws_payload_types";

export type AdaptedSpectrum = {
  freq: number[];
  combined: number[];
  strength_metrics: Record<string, unknown>;
};

export type ClientInfo = {
  id: string;
  name: string;
  last_seen_age_ms: number;
  sample_rate_hz: number;
  location: string;
  firmware_version: string;
  [key: string]: unknown;
};

export type DiagnosticEvent = {
  event_id: string;
  kind: string;
  class_key: string;
  severity_key: string;
  sensor_id: string;
  sensor_label: string;
  sensor_labels: string[];
  sensor_count: number;
  peak_hz: number;
  peak_amp: number;
  peak_amp_g: number;
  vibration_strength_db: number;
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
  order_bands: OrderBand[] | null;
};

export type OrderBand = {
  key: string;
  center_hz: number;
  tolerance: number;
};

export type AdaptedPayload = {
  clients: ClientInfo[];
  speed_mps: number | null;
  rotational_speeds: RotationalSpeeds | null;
  diagnostics: {
    diagnostics_sequence: number;
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

let _schemaWarningLogged = false;

export function adaptServerPayload(payload: Record<string, unknown>): AdaptedPayload {
  if (!payload || typeof payload !== "object") {
    throw new Error("Missing websocket payload.");
  }

  // Schema version check: warn once if unknown, but continue decoding.
  const schemaVersion = typeof payload.schema_version === "string" ? payload.schema_version : undefined;
  if (schemaVersion !== undefined && schemaVersion !== EXPECTED_SCHEMA_VERSION && !_schemaWarningLogged) {
    _schemaWarningLogged = true;
    console.error(
      `[VibeSensor] Unknown WS payload schema_version "${schemaVersion}" ` +
      `(expected "${EXPECTED_SCHEMA_VERSION}"). The dashboard may not display correctly. ` +
      `Update the UI to match the server version.`,
    );
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

  const rawClients = Array.isArray(payload.clients) ? (payload.clients as Record<string, unknown>[]) : [];
  // Remap server field names to UI-internal field names
  const clients: ClientInfo[] = rawClients.map((c) => {
    const mapped = { ...c } as ClientInfo;
    // Server sends "location", UI uses "location_code" in ClientRow
    if ("location" in c && !("location_code" in c)) {
      (mapped as unknown as Record<string, unknown>).location_code = c.location;
    }
    return mapped;
  });

  const adapted: AdaptedPayload = {
    clients,
    speed_mps: typeof payload.speed_mps === "number" ? payload.speed_mps : null,
    rotational_speeds: null,
    diagnostics: {
      diagnostics_sequence: typeof diagnostics.diagnostics_sequence === "number" ? diagnostics.diagnostics_sequence : -1,
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
    let orderBands: OrderBand[] | null = null;
    if (Array.isArray(rotational.order_bands)) {
      orderBands = (rotational.order_bands as Record<string, unknown>[])
        .filter((b) => b && typeof b === "object" && typeof b.key === "string" && typeof b.center_hz === "number" && typeof b.tolerance === "number")
        .map((b) => ({ key: String(b.key), center_hz: Number(b.center_hz), tolerance: Number(b.tolerance) }));
    }
    adapted.rotational_speeds = {
      basis_speed_source: typeof rotational.basis_speed_source === "string" ? rotational.basis_speed_source : null,
      wheel: adaptRotationalSpeedValue(rotational.wheel),
      driveshaft: adaptRotationalSpeedValue(rotational.driveshaft),
      engine: adaptRotationalSpeedValue(rotational.engine),
      order_bands: orderBands,
    };
  }

  if (payload.spectra && typeof payload.spectra === "object") {
    const spectraObj = payload.spectra as Record<string, unknown>;
    // Shared frequency axis: used when all clients share the same axis.
    const sharedFreq = asNumberArray(spectraObj.freq);
    const clientsMap = spectraObj.clients;
    if (clientsMap && typeof clientsMap === "object") {
      adapted.spectra = { clients: {} };
      for (const [clientId, spectrum] of Object.entries(clientsMap as Record<string, unknown>)) {
        if (!spectrum || typeof spectrum !== "object") continue;
        const specObj = spectrum as Record<string, unknown>;
        // Prefer per-client freq (present only on mismatch), fall back to shared.
        const rawPerClientFreq = specObj.freq;
        const hasPerClientFreq = Array.isArray(rawPerClientFreq) && rawPerClientFreq.length > 0;
        const freq = hasPerClientFreq ? asNumberArray(rawPerClientFreq) : sharedFreq;
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
  }

  return adapted;
}

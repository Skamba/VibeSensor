import {
  EXPECTED_SCHEMA_VERSION,
  type LiveWsPayload,
  type WsClientInfo,
  type WsOrderBand,
  type WsRotationalSpeedValue,
  type WsRotationalSpeeds,
} from "./contracts/ws_payload_types";
import type { SpectrumClientData } from "./app/ui_app_state";
import { validateLiveWsPayload } from "./ws_payload_validator";

export type AdaptedClient = Pick<
  WsClientInfo,
  | "id"
  | "name"
  | "connected"
  | "mac_address"
  | "location_code"
  | "last_seen_age_ms"
  | "dropped_frames"
  | "frames_total"
  | "sample_rate_hz"
  | "firmware_version"
>;

export type RotationalSpeedValue = WsRotationalSpeedValue;

export type RotationalSpeeds = WsRotationalSpeeds;

export type OrderBand = WsOrderBand;

export type AdaptedPayload = {
  clients: AdaptedClient[];
  speed_mps: number | null;
  rotational_speeds: RotationalSpeeds | null;
  spectra: {
    clients: Record<string, SpectrumClientData>;
  } | null;
};

function adaptSpectra(spectra: LiveWsPayload["spectra"]): AdaptedPayload["spectra"] | null {
  if (!spectra?.clients) return null;
  const sharedFreq = spectra.freq ?? [];

  const adaptedClients: Record<string, SpectrumClientData> = {};
  for (const [clientId, spectrum] of Object.entries(spectra.clients)) {
    const rawPerClientFreq = spectrum.freq ?? [];
    const freq = rawPerClientFreq.length > 0 ? rawPerClientFreq : sharedFreq;
    const combined = spectrum.combined_spectrum_amp_g ?? [];
    const strengthMetrics = spectrum.strength_metrics ?? null;
    if (!freq.length || !combined.length || strengthMetrics === null || freq.length !== combined.length) {
      continue;
    }
    adaptedClients[clientId] = {
      freq,
      combined,
      strength_metrics: strengthMetrics,
    };
  }

  return { clients: adaptedClients };
}

let schemaWarningLogged = false;

function warnOnUnknownSchemaVersion(schemaVersion: string | null): void {
  if (
    schemaVersion !== null &&
    schemaVersion !== EXPECTED_SCHEMA_VERSION &&
    !schemaWarningLogged
  ) {
    schemaWarningLogged = true;
    console.error(
      `[VibeSensor] Unknown WS payload schema_version "${schemaVersion}" ` +
      `(expected "${EXPECTED_SCHEMA_VERSION}"). The dashboard may not display correctly. ` +
      "Update the UI to match the server version.",
    );
  }
}

export function adaptServerPayload(payload: unknown): AdaptedPayload {
  if (payload === null || typeof payload !== "object") {
    throw new Error("Missing websocket payload.");
  }

  const validatedPayload = validateLiveWsPayload(payload);
  warnOnUnknownSchemaVersion(validatedPayload.schema_version ?? null);

  return {
    clients: validatedPayload.clients ?? [],
    speed_mps: validatedPayload.speed_mps ?? null,
    rotational_speeds: validatedPayload.rotational_speeds ?? null,
    spectra: adaptSpectra(validatedPayload.spectra),
  };
}

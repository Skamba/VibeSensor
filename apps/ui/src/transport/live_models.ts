import {
  EXPECTED_SCHEMA_VERSION,
  type StrengthMetricsPayload,
  type WsClientInfo,
  type WsRotationalSpeeds,
} from "../contracts/ws_payload_types";

export const EXPECTED_LIVE_PAYLOAD_SCHEMA_VERSION = EXPECTED_SCHEMA_VERSION;

export type StrengthMetrics = StrengthMetricsPayload;

export interface SpectrumClientData {
  freq: number[];
  strength_metrics: StrengthMetrics;
  combined: number[];
}

export interface SpectrumFrameData {
  frame_fingerprint?: string | null;
  clients: Record<string, SpectrumClientData>;
}

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
  | "frame_samples"
  | "sample_rate_hz"
  | "firmware_version"
>;

export type RotationalSpeeds = WsRotationalSpeeds;

export interface AdaptedPayload {
  clients: AdaptedClient[];
  speed_mps: number | null;
  rotational_speeds: RotationalSpeeds | null;
  spectra: SpectrumFrameData | null;
}

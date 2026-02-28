/**
 * TypeScript types matching the server's LiveWsPayload Pydantic model.
 *
 * These types are derived from the JSON Schema at
 * apps/ui/src/contracts/ws_payload_schema.json and must stay in sync.
 *
 * When the server bumps SCHEMA_VERSION, update EXPECTED_SCHEMA_VERSION
 * here and adjust the decoding logic in server_payload.ts.
 */

/** Current schema version the frontend expects. */
export const EXPECTED_SCHEMA_VERSION = "1";

export interface WsSpectrumSeries {
  x: number[];
  y: number[];
  z: number[];
  combined_spectrum_amp_g: number[];
  strength_metrics: Record<string, unknown>;
  /** Per-client freq axis; present only when axes differ across clients. */
  freq?: number[] | null;
}

export interface WsAlignmentInfo {
  overlap_ratio: number;
  aligned: boolean;
  shared_window_s: number;
  sensor_count: number;
  clock_synced: boolean;
}

export interface WsFrequencyWarning {
  code: string;
  message: string;
  client_ids: string[];
}

export interface WsSpectraPayload {
  /** Shared frequency axis (non-empty when all clients share the same axis). */
  freq: number[];
  clients: Record<string, WsSpectrumSeries>;
  alignment?: WsAlignmentInfo | null;
  warning?: WsFrequencyWarning | null;
}

export interface WsRotationalSpeedValue {
  rpm: number | null;
  mode: string | null;
  reason: string | null;
}

export interface WsOrderBand {
  key: string;
  center_hz: number;
  tolerance: number;
}

export interface WsRotationalSpeeds {
  basis_speed_source: string | null;
  wheel: WsRotationalSpeedValue;
  driveshaft: WsRotationalSpeedValue;
  engine: WsRotationalSpeedValue;
  order_bands: WsOrderBand[] | null;
}

export interface WsClientInfo {
  id: string;
  name: string;
  last_seen_age_ms: number;
  sample_rate_hz: number;
  location: string;
  firmware_version: string;
  [key: string]: unknown;
}

export interface LiveWsPayload {
  schema_version: string;
  server_time: string;
  speed_mps: number | null;
  clients: WsClientInfo[];
  selected_client_id: string | null;
  rotational_speeds: WsRotationalSpeeds | null;
  spectra: WsSpectraPayload | null;
  diagnostics: Record<string, unknown>;
  [key: string]: unknown;
}

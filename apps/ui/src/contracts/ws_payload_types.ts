// Generated from vibesensor.cli.ws_schema_export
// Do not edit manually; run make sync-contracts

export interface components {
    schemas: {
        LiveWsPayload: {
            clients: components["schemas"]["ClientApiRow"][];
            rotational_speeds: components["schemas"]["RotationalSpeedsPayload"] | null;
            schema_version: string;
            selected_client_id: string | null;
            server_time: string;
            spectra?: components["schemas"]["SpectraPayload"];
            speed_mps: number | null;
        };
        ClientApiRow: {
            connected: boolean;
            dropped_frames: number;
            firmware_status: components["schemas"]["FirmwareStatus"];
            firmware_version: string;
            frame_loss_recent: boolean;
            frame_samples: number;
            frames_total: number;
            id: string;
            last_seen_age_ms: number | null;
            location_code: string;
            mac_address: string;
            name: string;
            sample_rate_hz: number;
        };
        FirmwareStatus: "current" | "outdated" | "unknown";
        OrderBandPayload: {
            center_hz: number;
            code: string;
            firing?: boolean;
            key: string;
            tolerance: number;
        };
        RotationalSpeedValuePayload: {
            mode: string | null;
            reason: string | null;
            rpm: number | null;
        };
        RotationalSpeedsPayload: {
            basis_speed_source: string | null;
            driveshaft: components["schemas"]["RotationalSpeedValuePayload"];
            engine: components["schemas"]["RotationalSpeedValuePayload"];
            order_bands: components["schemas"]["OrderBandPayload"][] | null;
            wheel: components["schemas"]["RotationalSpeedValuePayload"];
        };
        SpectraPayload: {
            clients?: {
                [key: string]: components["schemas"]["SpectrumSeriesPayload"];
            };
            frame_fingerprint?: string;
            freq?: number[];
        };
        SpectrumSeriesPayload: {
            combined_spectrum_amp_g?: number[];
            freq?: number[];
            peak_mg?: number;
            strength_metrics?: components["schemas"]["VibrationStrengthMetrics"];
        };
        StrengthPeak: {
            amp: number;
            hz: number;
            local_floor_amp_g?: number;
            strength_bucket: string | null;
            vibration_strength_db: number;
        };
        VibrationStrengthMetrics: {
            noise_floor_amp_g: number;
            peak_amp_g: number;
            strength_bucket: string | null;
            top_peaks: components["schemas"]["StrengthPeak"][];
            vibration_strength_db: number;
        };
    };
}

export const EXPECTED_SCHEMA_VERSION = "1" as const;

type WsSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type StrengthMetricPeak = WsSchema<"StrengthPeak">;
export type StrengthMetricsPayload = WsSchema<"VibrationStrengthMetrics">;
export type WsSpectrumSeries = WsSchema<"SpectrumSeriesPayload">;
export type WsSpectraPayload = WsSchema<"SpectraPayload">;
export type WsRotationalSpeedValue = WsSchema<"RotationalSpeedValuePayload">;
export type WsOrderBand = WsSchema<"OrderBandPayload">;
export type WsRotationalSpeeds = WsSchema<"RotationalSpeedsPayload">;
export type WsClientInfo = WsSchema<"ClientApiRow">;
export type LiveWsPayload = WsSchema<"LiveWsPayload">;

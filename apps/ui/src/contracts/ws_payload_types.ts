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
        AlignmentInfoPayload: {
            aligned: boolean;
            clock_synced: boolean;
            overlap_ratio: number;
            sensor_count: number;
            shared_window_s: number;
        };
        AxisMetrics: {
            p2p: number;
            peaks: components["schemas"]["AxisPeak"][];
            rms: number;
        };
        AxisPeak: {
            amp?: number;
            hz?: number;
            snr_ratio?: number;
        };
        ClientApiRow: {
            connected: boolean;
            dropped_frames: number;
            firmware_version: string;
            frame_samples: number;
            frames_total: number;
            id: string;
            last_reset_time?: number | null;
            last_seen_age_ms: number | null;
            latest_metrics?: components["schemas"]["ClientMetrics"];
            location_code: string;
            mac_address: string;
            name: string;
            reset_count?: number;
            sample_rate_hz: number;
        };
        ClientMetrics: {
            combined?: components["schemas"]["CombinedMetrics"];
            x?: components["schemas"]["AxisMetrics"];
            y?: components["schemas"]["AxisMetrics"];
            z?: components["schemas"]["AxisMetrics"];
        };
        CombinedMetrics: {
            filter_chain?: components["schemas"]["ProcessingFilterId"][];
            peaks?: components["schemas"]["StrengthPeak"][];
            processing_profile?: components["schemas"]["ProcessingProfile"];
            strength_metrics?: components["schemas"]["VibrationStrengthMetrics"];
            vib_mag_p2p?: number;
            vib_mag_rms?: number;
            window_quality?: components["schemas"]["WindowQualityPayload"];
        };
        FrequencyWarningPayload: {
            client_ids: string[];
            code: string;
            message: string;
        };
        OrderBandPayload: {
            center_hz: number;
            key: string;
            tolerance: number;
        };
        ProcessingFilterId: "median_3_sample_time_domain";
        ProcessingProfile: "live_display" | "diagnostic_raw" | "diagnostic_filtered";
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
            alignment?: components["schemas"]["AlignmentInfoPayload"];
            clients?: {
                [key: string]: components["schemas"]["SpectrumSeriesPayload"];
            };
            frame_fingerprint?: string;
            freq?: number[];
            warning?: components["schemas"]["FrequencyWarningPayload"];
        };
        SpectrumSeriesPayload: {
            combined_spectrum_amp_g?: number[];
            freq?: number[];
            strength_metrics?: components["schemas"]["VibrationStrengthMetrics"];
        };
        StrengthPeak: {
            amp: number;
            hz: number;
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
        WindowQualityPayload: {
            clipping_axis_counts: {
                [key: string]: number;
            };
            clipping_sample_count: number;
            clipping_sample_ratio: number;
            clipping_score: number;
            context_score: number;
            frequency_stability_score: number;
            mounting_high_frequency_ratio: number | null;
            mounting_score: number;
            packet_integrity_score: number;
            reasons: string[];
            sample_completeness_score: number;
            score: number;
            shock_broadband_ratio: number | null;
            shock_crest_factor: number | null;
            state: string;
            timing_integrity_score: number;
            transient_score: number;
        };
    };
}

export const EXPECTED_SCHEMA_VERSION = "1" as const;

type WsSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type StrengthMetricPeak = WsSchema<"StrengthPeak">;
export type StrengthMetricsPayload = WsSchema<"VibrationStrengthMetrics">;
export type WsSpectrumSeries = WsSchema<"SpectrumSeriesPayload">;
export type WsAlignmentInfo = WsSchema<"AlignmentInfoPayload">;
export type WsFrequencyWarning = WsSchema<"FrequencyWarningPayload">;
export type WsSpectraPayload = WsSchema<"SpectraPayload">;
export type WsRotationalSpeedValue = WsSchema<"RotationalSpeedValuePayload">;
export type WsOrderBand = WsSchema<"OrderBandPayload">;
export type WsRotationalSpeeds = WsSchema<"RotationalSpeedsPayload">;
export type WsClientInfo = WsSchema<"ClientApiRow">;
export type LiveWsPayload = WsSchema<"LiveWsPayload">;

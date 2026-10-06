// Generated from vibesensor.cli.http_api_schema_export
// Do not edit manually; run make sync-contracts

export interface components {
    schemas: {
        /** Request body for selecting the active car profile. */
        ActiveCarRequest: {
            car_id: string;
        };
        AmplitudeBasis: "order" | "overall";
        /** HTTP contract for finding amplitude/strength metadata. */
        AmplitudeMetric: {
            definition?: components["schemas"]["JsonSchemaValue"];
            name?: string | null;
            units?: string | null;
            value?: number | null;
        };
        /** Structured partial payload for analysis-setting updates and car aspects. */
        AnalysisSettingsPayload: {
            current_gear_ratio?: number | null;
            default_axle_for_speed?: components["schemas"]["TireSpeedAxle"];
            final_drive_ratio?: number | null;
            final_drive_uncertainty_pct?: number;
            front_rim_in?: number;
            front_tire_aspect_pct?: number;
            front_tire_width_mm?: number;
            gear_uncertainty_pct?: number;
            rear_rim_in?: number;
            rear_tire_aspect_pct?: number;
            rear_tire_width_mm?: number;
            rim_in?: number;
            speed_uncertainty_pct?: number;
            tire_aspect_pct?: number;
            tire_deflection_factor?: number;
            tire_diameter_uncertainty_pct?: number;
            tire_width_mm?: number;
        };
        /** Request body for updating vehicle analysis settings (tire geometry, gear ratios, etc.). */
        AnalysisSettingsRequest: {
            current_gear_ratio?: number | null;
            default_axle_for_speed?: ("front" | "rear" | "average") | null;
            final_drive_ratio?: number | null;
            final_drive_uncertainty_pct?: number | null;
            front_rim_in?: number | null;
            front_tire_aspect_pct?: number | null;
            front_tire_width_mm?: number | null;
            gear_uncertainty_pct?: number | null;
            rear_rim_in?: number | null;
            rear_tire_aspect_pct?: number | null;
            rear_tire_width_mm?: number | null;
            rim_in?: number | null;
            speed_uncertainty_pct?: number | null;
            tire_aspect_pct?: number | null;
            tire_deflection_factor?: number | null;
            tire_diameter_uncertainty_pct?: number | null;
            tire_width_mm?: number | null;
        };
        /** Response body reflecting the current validated analysis settings. */
        AnalysisSettingsResponse: {
            current_gear_ratio?: number | null;
            default_axle_for_speed: "front" | "rear" | "average";
            final_drive_ratio?: number | null;
            final_drive_uncertainty_pct: number;
            front_rim_in?: number | null;
            front_tire_aspect_pct?: number | null;
            front_tire_width_mm?: number | null;
            gear_uncertainty_pct: number;
            rear_rim_in?: number | null;
            rear_tire_aspect_pct?: number | null;
            rear_tire_width_mm?: number | null;
            rim_in?: number | null;
            speed_uncertainty_pct: number;
            tire_aspect_pct?: number | null;
            tire_deflection_factor: number;
            tire_diameter_uncertainty_pct: number;
            tire_width_mm?: number | null;
        };
        /** Persisted analysis summary (``runs.analysis_json``) and its HTTP response schema. */
        AnalysisSummary: {
            accel_scale_g_per_lsb: number | null;
            analysis_metadata?: components["schemas"]["PayloadObject"];
            case_id?: string | null;
            data_quality: components["schemas"]["DataQualityResponse"];
            diagnosis: components["schemas"]["DiagnosisPayload"];
            duration_s: number;
            end_time_utc?: string | null;
            feature_interval_s: number | null;
            fft_window_size_samples?: number | null;
            fft_window_type?: string | null;
            file_name: string;
            findings: components["schemas"]["FindingPayload"][];
            firmware_version?: string | null;
            incomplete_for_order_analysis: boolean;
            lang: string;
            metadata: components["schemas"]["PayloadObject"];
            most_likely_origin: components["schemas"]["SuspectedVibrationOriginPayload"];
            peak_picker_method?: string | null;
            phase_info: components["schemas"]["PhaseInfoResponse"];
            phase_segments: components["schemas"]["PhaseSegmentSummaryResponse"][];
            phase_speed_breakdown: components["schemas"]["PhaseSpeedBreakdownRow"][];
            phase_timeline: components["schemas"]["PhaseTimelineEntryResponse"][];
            plots?: components["schemas"]["PlotDataResult"] | null;
            raw_sample_rate_hz: number | null;
            record_length: string;
            report_date?: string | null;
            rows: number;
            run_id: string;
            run_noise_baseline_db: number | null;
            run_suitability: components["schemas"]["RunSuitabilityCheck"][];
            samples?: components["schemas"]["PayloadObject"][];
            sensor_count_used: number;
            sensor_intensity_by_location: components["schemas"]["LocationIntensitySummaryResponse"][];
            sensor_locations: string[];
            sensor_locations_connected_throughout: string[];
            sensor_model?: string | null;
            speed_breakdown: components["schemas"]["SpeedBreakdownRow"][];
            speed_breakdown_skipped_reason: components["schemas"]["PayloadObject"] | null;
            speed_stats: components["schemas"]["SpeedStatsResponse"];
            speed_stats_by_phase: {
                [key: string]: components["schemas"]["SpeedStatsResponse"];
            };
            start_time_utc?: string | null;
            top_causes: components["schemas"]["FindingPayload"][];
            warnings: components["schemas"]["SummaryWarningResponse"][];
        };
        ApiPayloadObject: {
            [key: string]: components["schemas"]["JsonSchemaValue"];
        };
        /** The browser's clock and IANA time zone, reported when the UI connects. */
        BrowserClockRequest: {
            epoch_ms: number;
            time_zone?: string | null;
        };
        /** What the server did with the reported clock, and the stored time zone. */
        BrowserClockResponse: {
            action: "stepped" | "within_threshold" | "ntp_synchronized" | "sync_state_unknown" | "recording" | "already_stepped" | "not_permitted";
            offset_s: number;
            runs_corrected: number;
            time_zone: string | null;
        };
        /** One car profile as persisted in the settings snapshot and served over HTTP. */
        CarConfigPayload: {
            aspects: components["schemas"]["AnalysisSettingsPayload"];
            drive_layout?: ("FWD" | "RWD" | "AWD") | null;
            final_drive_axle?: ("front" | "rear") | null;
            fuel_type?: ("ICE" | "PHEV" | "EV") | null;
            id: string;
            name: string;
            order_reference_status?: components["schemas"]["CarOrderReferenceStatusPayload"] | null;
            type: string;
            variant?: string | null;
        };
        /** Create/update request body for one car profile; omitted or null fields stay unchanged. */
        CarConfigUpdatePayload: {
            aspects?: components["schemas"]["AnalysisSettingsPayload"] | null;
            drive_layout?: ("FWD" | "RWD" | "AWD") | null;
            final_drive_axle?: ("front" | "rear") | null;
            fuel_type?: ("ICE" | "PHEV" | "EV") | null;
            name?: string | null;
            order_reference_status?: components["schemas"]["CarOrderReferenceStatusPayload"] | null;
            type?: string | null;
            variant?: string | null;
        };
        /** Response body listing available car manufacturer brands. */
        CarLibraryBrandsResponse: {
            brands: string[];
        };
        /** A gearbox option from the car library (gear ratios). */
        CarLibraryGearboxEntry: {
            /** The axle the final drive belongs to; `null` when the library row doesn't say (an all-wheel-drive row with one published axle ratio). */
            final_drive_axle?: ("front" | "rear") | null;
            /** `null` when the library has no final drive for this gearbox. */
            final_drive_ratio: number | null;
            final_drive_ratio_confidence?: string | null;
            fuel_type: "ICE" | "PHEV" | "EV";
            gear_ratios?: number[] | null;
            gear_ratios_confidence?: string | null;
            name: string;
            requires_manual_confirmation?: boolean | null;
            source_status?: "exact_row" | null;
            /** `null` when the library has no top gear for this gearbox. */
            top_gear_ratio: number | null;
            top_gear_ratio_confidence?: string | null;
            transmission_confidence?: string | null;
        };
        /**
         * A full car library entry with brand, model, tire options, and variants.
         *
         * One entry per model generation; ``model`` names the generation code and
         * its model years, e.g. ``"X1 (F48, 2015–2022)"``.
         */
        CarLibraryModelEntry: {
            brand: string;
            gearboxes: components["schemas"]["CarLibraryGearboxEntry"][];
            model: string;
            rim_in: number;
            tire_aspect_pct: number;
            tire_options: components["schemas"]["CarLibraryTireOptionEntry"][];
            tire_width_mm: number;
            type: string;
            variants?: components["schemas"]["CarLibraryVariantEntry"][];
        };
        /** Response body listing car library model entries. */
        CarLibraryModelsResponse: {
            models: components["schemas"]["CarLibraryModelEntry"][];
        };
        /** One axle's tire dimensions. */
        CarLibraryTireDimensionsEntry: {
            aspect_pct: number;
            rim_in: number;
            width_mm: number;
        };
        /** A tire size option from the car library. */
        CarLibraryTireOptionEntry: {
            default_axle_for_speed: "front" | "rear" | "average";
            front: components["schemas"]["CarLibraryTireDimensionsEntry"];
            name: string;
            rear?: components["schemas"]["CarLibraryTireDimensionsEntry"] | null;
            rim_in: number;
            source_confidence?: string | null;
            tire_aspect_pct: number;
            tire_width_mm: number;
        };
        /** Response body listing available car body types. */
        CarLibraryTypesResponse: {
            types: string[];
        };
        /**
         * A specific variant/trim of a car library model entry.
         *
         * A variant whose rows differ only by model year is split into one entry
         * per model-year period, named with its years (``"xDrive25d (2021–2022)"``).
         */
        CarLibraryVariantEntry: {
            drivetrain: "FWD" | "RWD" | "AWD";
            engine?: string | null;
            gearboxes?: components["schemas"]["CarLibraryGearboxEntry"][] | null;
            name: string;
            /** Last model year of the variant's rows. */
            production_end_year?: number | null;
            /** First model year of the variant's rows. */
            production_start_year?: number | null;
            rim_in?: number | null;
            tire_aspect_pct?: number | null;
            tire_options?: components["schemas"]["CarLibraryTireOptionEntry"][] | null;
            tire_width_mm?: number | null;
        };
        /**
         * Persisted/HTTP confidence metadata for selected drivetrain order-reference values.
         *
         * Confidence values stay plain strings at this boundary;
         * ``car_order_reference_status_from_mapping`` keeps only the known vocabulary.
         */
        CarOrderReferenceStatusPayload: {
            current_gear_ratio_confidence?: string | null;
            final_drive_ratio_confidence?: string | null;
            requires_manual_confirmation: boolean;
            selection_source_status: "exact_row" | "manual_entry";
            tire_dimensions_confidence?: string | null;
            transmission_confidence?: string | null;
            transmission_name?: string | null;
        };
        /** Car profiles plus the active selection, as held in memory and served over HTTP. */
        CarsSnapshot: {
            active_car_id: string | null;
            cars: components["schemas"]["CarConfigPayload"][];
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
        /** Response body with available sensor-location options. */
        ClientLocationsResponse: {
            locations: components["schemas"]["LocationOptionResponse"][];
        };
        /** Response body listing known sensor clients and their live connection state. */
        ClientsResponse: {
            clients: components["schemas"]["ClientApiRow"][];
        };
        ConfidenceLevelValue: "strong" | "moderate" | "weak";
        /** Response body for acceleration sanity diagnostics. */
        DataQualityAccelSanityResponse: {
            saturation_count: number | null;
            sensor_limit: number | null;
            x_mean: number | null;
            x_variance: number | null;
            y_mean: number | null;
            y_variance: number | null;
            z_mean: number | null;
            z_variance: number | null;
        };
        /** Response body for grouped outlier summaries. */
        DataQualityOutliersResponse: {
            accel_magnitude: components["schemas"]["OutlierSummaryResponse"];
            amplitude_metric: components["schemas"]["OutlierSummaryResponse"];
        };
        /** Response body for required-field missing percentages. */
        DataQualityRequiredMissingPctResponse: {
            accel_x: number;
            accel_y: number;
            accel_z: number;
            speed_kmh: number;
            t_s: number;
        };
        /** Response body for run-level data-quality diagnostics. */
        DataQualityResponse: {
            accel_sanity: components["schemas"]["DataQualityAccelSanityResponse"];
            outliers: components["schemas"]["DataQualityOutliersResponse"];
            required_missing_pct: components["schemas"]["DataQualityRequiredMissingPctResponse"];
            speed_coverage: components["schemas"]["DataQualitySpeedCoverageResponse"];
        };
        /** Response body for summarized speed-coverage statistics. */
        DataQualitySpeedCoverageResponse: {
            count_non_null: number;
            max_kmh: number | null;
            mean_kmh: number | null;
            min_kmh: number | null;
            non_null_pct: number;
            stddev_kmh: number | null;
        };
        /** Response body confirming deletion of a history run. */
        DeleteHistoryRunResponse: {
            run_id: string;
            status: string;
        };
        /** The run verdict, its single confidence level, and the evidence behind it. */
        DiagnosisPayload: {
            amplitude_basis: components["schemas"]["AmplitudeBasis"];
            amplitude_vs_speed: components["schemas"]["SpeedAmplitudePoint"][];
            conditions: components["schemas"]["TestConditions"];
            confidence_level: components["schemas"]["ConfidenceLevelValue"] | null;
            dominant_phase: string | null;
            driveline_parts?: components["schemas"]["DrivelinePart"][];
            finding_id: string | null;
            frequency_hz: number | null;
            guided_phases: components["schemas"]["GuidedPhaseValue"][];
            location: string | null;
            location_amplitudes: components["schemas"]["LocationAmplitudeRow"][];
            order_code: components["schemas"]["OrderCodeValue"] | null;
            order_findings: components["schemas"]["OrderFindingRow"][];
            presence_ratio: number | null;
            reference_speed_kmh: number | null;
            source: string | null;
            source_checks: components["schemas"]["SourceCheck"][];
            spectrum: components["schemas"]["DiagnosisSpectrum"] | null;
            speed_dependence: components["schemas"]["SpeedDependenceValue"] | null;
            speed_max_kmh: number | null;
            speed_min_kmh: number | null;
            unexplained_vibration: boolean;
            verdict: components["schemas"]["DiagnosisVerdictValue"];
            weak_reasons: string[];
            zone: string | null;
        };
        /** Recurring peaks at one location within one speed window, with order markers. */
        DiagnosisSpectrum: {
            floor_mg: number | null;
            location: string;
            order_markers: {
                [key: string]: number;
            };
            peaks: components["schemas"]["SpectrumPeak"][];
            speed_max_kmh: number;
            speed_min_kmh: number;
        };
        DiagnosisVerdictValue: "fault" | "weak_evidence" | "no_fault";
        DriveLayoutValue: "FWD" | "RWD" | "AWD";
        DrivelineCapability: "ok" | "estimated_final_drive" | "missing_final_drive" | "missing_tire" | "manual_speed";
        DrivelinePart: "front_drive" | "propshaft_rear";
        EngineCapability: "measured" | "estimated_top_gear" | "hybrid_estimated" | "estimated_ratios" | "missing_tire" | "missing_final_drive" | "missing_top_gear" | "missing_ratios" | "manual_speed" | "not_applicable";
        /** Response body confirming whether an ESP32 flash job was cancelled. */
        EspFlashCancelResponse: {
            cancelled: boolean;
        };
        /** Response body for a single historical ESP32 flash job. */
        EspFlashHistoryEntryResponse: {
            auto_detect: boolean;
            error?: string | null;
            exit_code?: number | null;
            finished_at?: number | null;
            job_id: number;
            selected_port?: string | null;
            started_at: number;
            state: string;
        };
        /** Response body listing all past ESP32 flash job attempts. */
        EspFlashHistoryResponse: {
            attempts: components["schemas"]["EspFlashHistoryEntryResponse"][];
        };
        /** Response body with a page of ESP32 flash log lines. */
        EspFlashLogsResponse: {
            from_index: number;
            lines: string[];
            next_index: number;
        };
        /** Response body listing detected serial ports for ESP32 flashing. */
        EspFlashPortsResponse: {
            ports: components["schemas"]["EspSerialPortResponse"][];
        };
        /** Request body to start an ESP32 firmware flash job. */
        EspFlashStartRequest: {
            auto_detect: boolean;
            port?: string | null;
        };
        /** Response body confirming that an ESP32 flash job has been queued. */
        EspFlashStartResponse: {
            job_id: number;
            status: string;
        };
        /** Response body for the current ESP32 flash job status. */
        EspFlashStatusResponse: {
            auto_detect: boolean;
            error?: string | null;
            exit_code?: number | null;
            finished_at?: number | null;
            job_id?: number | null;
            last_success_at?: number | null;
            log_count: number;
            phase: string;
            selected_port?: string | null;
            started_at?: number | null;
            state: string;
        };
        /** Response body describing a single detected serial port. */
        EspSerialPortResponse: {
            description: string;
            pid?: number | null;
            port: string;
            serial_number?: string | null;
            vid?: number | null;
        };
        ExpectedFrameLoss: "stream_start" | "bluetooth_scan" | "bluetooth_pairing";
        FinalDriveAxleValue: "front" | "rear";
        /** HTTP contract for serialized evidence metrics attached to a finding. */
        FindingEvidenceMetrics: {
            burstiness?: number | null;
            focused_speed_band?: string | null;
            frequency_correlation?: number | null;
            global_match_rate?: number | null;
            match_rate?: number | null;
            matched_samples?: number | null;
            max_intensity_db?: number | null;
            mean_noise_floor_db?: number | null;
            mean_relative_error?: number | null;
            median_intensity_db?: number | null;
            median_relative_to_run_noise?: number | null;
            p95_intensity_db?: number | null;
            p95_relative_to_run_noise?: number | null;
            per_phase_confidence?: {
                [key: string]: number;
            } | null;
            phases_with_evidence?: number | null;
            possible_samples?: number | null;
            presence_ratio?: number | null;
            run_noise_baseline_db?: number | null;
            sample_count?: number | null;
            snr_db?: number | null;
            spatial_concentration?: number | null;
            spatial_uniformity?: number | null;
            speed_uniformity?: number | null;
            total_samples?: number | null;
            vibration_strength_db?: number | null;
        };
        /**
         * Canonical shared contract for one serialized finding payload.
         *
         * Boundary serializers and HTTP models should import this TypedDict directly
         * so future field changes have one source of truth. It intentionally includes
         * a few presentation-oriented projections (``evidence_summary``,
         * ``frequency_hz_or_order``, ``amplitude_metric``, and the action-defined
         * ``confidence_level``) alongside the domain-owned finding data.
         */
        FindingPayload: {
            amplitude_metric: components["schemas"]["AmplitudeMetric"];
            confidence: number | null;
            confidence_level?: components["schemas"]["ConfidenceLevelValue"] | null;
            diffuse_excitation?: boolean | null;
            dominance_ratio?: number | null;
            dominant_phase?: string | null;
            evidence_metrics?: components["schemas"]["FindingEvidenceMetrics"] | null;
            evidence_summary: string;
            finding_id: string;
            finding_key?: string | null;
            finding_kind?: string | null;
            frequency_hz?: number | null;
            frequency_hz_or_order: number | string;
            location_hotspot?: components["schemas"]["LocationHotspotPayload"] | null;
            matched_points?: components["schemas"]["MatchedPoint"][];
            order?: string | null;
            peak_classification?: string | null;
            phase_evidence?: components["schemas"]["PhaseEvidence"] | null;
            ranking_score?: number | null;
            severity?: string | null;
            signatures_observed?: string[];
            strongest_location?: string | null;
            strongest_speed_band?: string | null;
            suspected_source: string;
            weak_spatial_separation?: boolean | null;
        };
        FirmwareStatus: "current" | "outdated" | "unknown";
        FuelTypeValue: "ICE" | "PHEV" | "EV";
        GuidedPhaseName: "sweep" | "hold" | "coast_down" | "brake";
        /** Request body that marks the guided test-drive step the driver starts now. */
        GuidedPhaseRequest: {
            /** `sweep`, `hold`, `coast_down`, or `brake`; `null` ends the guided test. */
            phase: components["schemas"]["GuidedPhaseName"] | null;
        };
        GuidedPhaseValue: "sweep" | "hold" | "coast_down" | "brake";
        HTTPValidationError: {
            detail?: components["schemas"]["ValidationError"][];
        };
        /** Response body for aggregated client data-loss counters. */
        HealthDataLossResponse: {
            affected_clients: number;
            buffer_overflow_drops: number;
            frames_dropped: number;
            parse_errors: number;
            queue_overflow_drops: number;
            server_queue_drops: number;
            tracked_clients: number;
        };
        HealthIngestClientResponse: {
            advertised_sample_rate_hz: number;
            client_id: string;
            duplicates_received: number;
            effective_sample_rate_hz: number | null;
            estimated_ingest_hz: number;
            expected_frames_dropped: number;
            firmware_status: components["schemas"]["FirmwareStatus"];
            firmware_version: string;
            frames_dropped: number;
            last_ack_latency_ms: number;
            last_expected_loss_reason: components["schemas"]["ExpectedFrameLoss"] | null;
            last_packet_queue_age_ms: number;
            late_packets: number;
            parse_errors: number;
            processed_packets: number;
            processed_samples: number;
            queue_overflow_drops: number;
            server_queue_drops: number;
            timing_min_lag_ms: number | null;
            timing_state: "unknown" | "ok" | "timestamp_lag" | "rate_mismatch";
        };
        HealthIngestResponse: {
            clients: components["schemas"]["HealthIngestClientResponse"][];
            raw_capture: components["schemas"]["HealthRawCaptureResponse"];
            udp: components["schemas"]["HealthUdpIngestResponse"];
            ws_publish: components["schemas"]["HealthWsPublishResponse"];
        };
        /** Response body for processing intake timing and throughput counters. */
        HealthIntakeStatsResponse: {
            last_compute_all_duration_s: number;
            last_compute_duration_s: number;
            last_ingest_duration_s: number;
            total_compute_calls: number;
            total_ingested_samples: number;
        };
        /** Response body for persistence health details. */
        HealthPersistenceResponse: {
            analysis_active_run_id?: string | null;
            analysis_elapsed_s?: number | null;
            analysis_in_progress: boolean;
            analysis_queue_depth: number;
            analysis_queue_max_depth: number;
            analysis_queue_oldest_age_s?: number | null;
            analysis_started_at?: number | null;
            analyzing_oldest_age_s?: number | null;
            analyzing_run_count: number;
            last_completed_run_error?: string | null;
            last_completed_run_id?: string | null;
            samples_dropped: number;
            samples_written: number;
            write_error: string | null;
        };
        HealthRawCaptureResponse: {
            dropped_chunks: number;
            pressure_state: "ok" | "warn" | "degraded";
            queue_depth: number;
            queue_max_depth: number;
            write_error_chunks: number;
        };
        /** Data loss in the last ``window_s`` seconds; health warnings use only these. */
        HealthRecentDataLossResponse: {
            buffer_overflow_drops: number;
            expected_frames_dropped: number;
            frame_loss_clients: number;
            frames_dropped: number;
            parse_errors: number;
            queue_overflow_drops: number;
            server_queue_drops: number;
            window_s: number;
        };
        /** Response body for the server health check endpoint. */
        HealthResponse: {
            background_task_failures: {
                [key: string]: string;
            };
            data_loss: components["schemas"]["HealthDataLossResponse"];
            db_corruption_detected: boolean;
            db_last_write_duration_s: number;
            db_max_write_duration_s: number;
            degradation_reasons: string[];
            frame_size_mismatch_count: number;
            ingest: components["schemas"]["HealthIngestResponse"];
            intake_stats: components["schemas"]["HealthIntakeStatsResponse"];
            max_tick_duration_s: number;
            persistence: components["schemas"]["HealthPersistenceResponse"];
            processing_failure_categories: {
                [key: string]: number;
            };
            processing_failures: number;
            processing_last_failure: string | null;
            processing_state: string;
            recent_data_loss: components["schemas"]["HealthRecentDataLossResponse"];
            root_side: components["schemas"]["HealthRootSideResponse"];
            sample_rate_mismatch_count: number;
            startup_error: string | null;
            startup_phase: string;
            startup_state: string;
            startup_warnings: string[];
            status: "ok" | "warn" | "degraded";
            subsystems: {
                [key: string]: components["schemas"]["HealthSubsystemResponse"];
            };
            tick_count: number;
            tick_duration_s: number;
        };
        /** Whether the installed root-side helpers and units match this release. */
        HealthRootSideResponse: {
            expected_digest: string;
            installed_digest: string | null;
            state: "current" | "outdated" | "not_installed";
        };
        HealthSubsystemResponse: {
            reason_codes: string[];
            status: "ready" | "degraded" | "unhealthy";
        };
        HealthUdpIngestResponse: {
            dropped_datagrams: number;
            enqueued_datagrams: number;
            last_ack_latency_ms: number;
            last_packet_queue_age_ms: number;
            max_ack_latency_ms: number;
            max_packet_queue_age_ms: number;
            processed_datagrams: number;
            queue_depth: number;
            queue_max_depth: number;
        };
        HealthWsPublishResponse: {
            active_connections: number;
            last_publish_duration_ms: number;
            max_publish_duration_ms: number;
            total_publish_ticks: number;
        };
        /** Response body describing persisted artifact availability for a history run. */
        HistoryArtifactAvailabilityResponse: {
            raw_capture: "not_recorded" | "pending" | "available" | "missing" | "degraded";
        };
        /** Response body describing one persisted run-finalization stage outcome. */
        HistoryFinalizationStageResponse: {
            artifacts_created?: string[];
            diagnostic_context?: components["schemas"]["ApiPayloadObject"];
            duration_ms: number;
            stage_name: string;
            status: "ok" | "skipped" | "degraded" | "failed";
            warnings?: string[];
        };
        /** Response body for a localized history/run trust warning. */
        HistoryInsightWarningResponse: {
            applies_to: string;
            code: string;
            detail?: string | null;
            severity: "warn" | "error";
            title: string;
        };
        /** Response body for a history run whose analysis is still in progress. */
        HistoryInsightsAnalyzingResponse: {
            run_id: string;
            status: "analyzing";
        };
        /** Response body for the localized history insights endpoint payload. */
        HistoryInsightsResponse: {
            accel_scale_g_per_lsb: number | null;
            analysis_metadata?: components["schemas"]["PayloadObject"];
            case_id?: string | null;
            data_quality: components["schemas"]["DataQualityResponse"];
            diagnosis: components["schemas"]["DiagnosisPayload"];
            duration_s: number;
            end_time_utc?: string | null;
            feature_interval_s: number | null;
            fft_window_size_samples?: number | null;
            fft_window_type?: string | null;
            file_name: string;
            findings: components["schemas"]["FindingPayload"][];
            firmware_version?: string | null;
            incomplete_for_order_analysis: boolean;
            lang: string;
            metadata: components["schemas"]["PayloadObject"];
            most_likely_origin: components["schemas"]["SuspectedVibrationOriginPayload"];
            peak_picker_method?: string | null;
            phase_info: components["schemas"]["PhaseInfoResponse"];
            phase_segments: components["schemas"]["PhaseSegmentSummaryResponse"][];
            phase_speed_breakdown: components["schemas"]["PhaseSpeedBreakdownRow"][];
            phase_timeline: components["schemas"]["PhaseTimelineEntryResponse"][];
            plots?: components["schemas"]["PlotDataResult"] | null;
            raw_sample_rate_hz: number | null;
            record_length: string;
            report_date?: string | null;
            rows: number;
            run_id: string;
            run_noise_baseline_db: number | null;
            run_suitability: components["schemas"]["RunSuitabilityCheck"][];
            samples?: components["schemas"]["PayloadObject"][];
            sensor_count_used: number;
            sensor_intensity_by_location: components["schemas"]["LocationIntensitySummaryResponse"][];
            sensor_locations: string[];
            sensor_locations_connected_throughout: string[];
            sensor_model?: string | null;
            speed_breakdown: components["schemas"]["SpeedBreakdownRow"][];
            speed_breakdown_skipped_reason: components["schemas"]["PayloadObject"] | null;
            speed_stats: components["schemas"]["SpeedStatsResponse"];
            speed_stats_by_phase: {
                [key: string]: components["schemas"]["SpeedStatsResponse"];
            };
            start_time_utc?: string | null;
            status: "complete";
            top_causes: components["schemas"]["FindingPayload"][];
            warnings?: components["schemas"]["HistoryInsightWarningResponse"][];
        };
        /** Response body for a single history-run list row. */
        HistoryListEntryResponse: {
            artifact_availability?: components["schemas"]["HistoryArtifactAvailabilityResponse"] | null;
            car_name?: string | null;
            created_at: string;
            end_time_utc?: string | null;
            error_message?: string | null;
            finalization_stages?: components["schemas"]["HistoryFinalizationStageResponse"][] | null;
            lifecycle?: components["schemas"]["HistoryRunLifecycleResponse"] | null;
            raw_capture_finalize?: components["schemas"]["HistoryRawCaptureFinalizeResponse"] | null;
            /** Accelerometer samples in the raw capture across all sensors; null when the run has no raw capture. */
            raw_sample_count?: number | null;
            run_id: string;
            /** The run started before the Pi clock was set (no NTP, no browser report), so start_time_utc and end_time_utc are wrong; the duration is right. */
            start_time_unverified: boolean;
            start_time_utc: string;
            status: string;
        };
        /** Response body listing recorded run summaries. */
        HistoryListResponse: {
            runs: components["schemas"]["HistoryListEntryResponse"][];
        };
        /** Response body describing the persisted raw-capture finalization outcome. */
        HistoryRawCaptureFinalizeResponse: {
            error_summary?: string | null;
            queue_depth?: number | null;
            status: "completed" | "not_configured" | "enqueue_timeout" | "timeout" | "failed";
        };
        /** Response body describing raw-capture loss policy for one run. */
        HistoryRawCaptureQualityResponse: {
            affected_sensor_count: number;
            max_sensor_drop_ratio: number;
            max_sensor_loss_events_per_minute: number;
            queue_overflow_chunk_count: number;
            queue_overflow_sensor_count: number;
            reason: string;
            severity: "ok" | "warn" | "degraded" | "fatal";
            total_chunk_count: number;
            total_dropped_chunk_count: number;
            total_loss_event_count: number;
        };
        /** Response body describing the canonical derived lifecycle for a history run. */
        HistoryRunLifecycleResponse: {
            post_analysis: "pending" | "running" | "ready" | "degraded";
            raw_capture: "not_recorded" | "pending" | "ready" | "degraded" | "missing";
            report: "pending" | "ready" | "degraded";
            stage: "recording" | "post_analysis_pending" | "post_analysis_running" | "post_analysis_ready" | "post_analysis_degraded";
        };
        /** Response body for a single history run with metadata and optional analysis. */
        HistoryRunResponse: {
            analysis?: components["schemas"]["AnalysisSummary"] | null;
            artifact_availability?: components["schemas"]["HistoryArtifactAvailabilityResponse"] | null;
            error_message?: string | null;
            fallback_reasons?: string[] | null;
            finalization_stages?: components["schemas"]["HistoryFinalizationStageResponse"][] | null;
            lifecycle?: components["schemas"]["HistoryRunLifecycleResponse"] | null;
            metadata?: components["schemas"]["ApiPayloadObject"];
            raw_capture_finalize?: components["schemas"]["HistoryRawCaptureFinalizeResponse"] | null;
            raw_capture_quality?: components["schemas"]["HistoryRawCaptureQualityResponse"] | null;
            run_id: string;
            sample_count: number;
            status: string;
        };
        /** Request body for the ``/api/clients/{id}/identify`` endpoint. */
        IdentifyRequest: {
            duration_ms: number;
        };
        /** Response body for a sensor identify (blink) command. */
        IdentifyResponse: {
            cmd_seq?: number | null;
            status: string;
        };
        JsonSchemaLeafObject: {
            [key: string]: components["schemas"]["JsonSchemaScalar"];
        };
        JsonSchemaNestedObject: {
            [key: string]: components["schemas"]["JsonSchemaNestedValue"];
        };
        JsonSchemaNestedValue: components["schemas"]["JsonSchemaScalar"] | components["schemas"]["JsonSchemaLeafObject"] | ((components["schemas"]["JsonSchemaScalar"] | components["schemas"]["JsonSchemaLeafObject"])[]);
        JsonSchemaScalar: boolean | number | string | null;
        JsonSchemaValue: components["schemas"]["JsonSchemaNestedValue"] | components["schemas"]["JsonSchemaNestedObject"] | ((components["schemas"]["JsonSchemaNestedValue"] | components["schemas"]["JsonSchemaNestedObject"])[]);
        LanguageCode: "en" | "nl";
        /** Request body for changing the UI language. */
        LanguageRequest: {
            language: components["schemas"]["LanguageCode"];
        };
        /** Response body confirming the active UI language. */
        LanguageResponse: {
            language: string;
        };
        /** Amplitude at one sensor location (mg, with dB above that location's floor). */
        LocationAmplitudeRow: {
            amplitude_mg: number | null;
            db_above_floor: number | null;
            location: string;
            presence_ratio: number | null;
            ratio_to_strongest: number | null;
        };
        /** HTTP contract for serialized location-hotspot evidence. */
        LocationHotspotPayload: {
            ambiguous_location?: boolean | null;
            ambiguous_locations?: string[];
            dominance_ratio?: number | null;
            localization_confidence?: number | null;
            location_count?: number | null;
            top_location?: string | null;
            weak_spatial_separation?: boolean | null;
        };
        /** Response body for one sensor-location intensity summary row. */
        LocationIntensitySummaryResponse: {
            dropped_frames_delta: number | null;
            location: string;
            max_intensity_db: number | null;
            mean_intensity_db: number | null;
            p50_intensity_db: number | null;
            p95_intensity_db: number | null;
            partial_coverage: boolean;
            phase_intensity?: {
                [key: string]: components["schemas"]["PhaseIntensityStatsResponse"];
            } | null;
            queue_overflow_drops_delta: number | null;
            sample_count: number;
            sample_coverage_ratio: number;
            sample_coverage_warning: boolean;
            strength_bucket_distribution: components["schemas"]["StrengthBucketDistributionResponse"];
            usable_sample_count?: number | null;
            usable_sample_coverage_ratio?: number | null;
            usable_sample_coverage_warning?: boolean | null;
        };
        /** A single sensor-location option (code + human-readable label). */
        LocationOptionResponse: {
            code: string;
            label: string;
        };
        /** HTTP contract for one serialized finding matched-point observation. */
        MatchedPoint: {
            amp?: number | null;
            heard?: boolean;
            location?: string | null;
            matched_hz?: number | null;
            phase?: string | null;
            predicted_hz?: number | null;
            rel_error?: number | null;
            speed_kmh?: number | null;
            t_s?: number | null;
        };
        /** Single discovered or configured Bluetooth OBD adapter. */
        ObdDeviceResponse: {
            connected: boolean;
            mac_address: string;
            name: string | null;
            paired: boolean;
            rfcomm_channel: number | null;
            trusted: boolean;
        };
        /** Request body for pairing and selecting a Bluetooth OBD adapter. */
        ObdPairRequest: {
            mac_address: string;
        };
        /** Response body after pairing and persisting a Bluetooth OBD adapter. */
        ObdPairResponse: {
            configured_device_mac: string;
            configured_device_name: string | null;
            connected: boolean;
            paired: boolean;
            rfcomm_channel: number | null;
            trusted: boolean;
        };
        /** Response body for a Bluetooth OBD discovery scan. */
        ObdScanResponse: {
            devices: components["schemas"]["ObdDeviceResponse"][];
        };
        /** Detailed Bluetooth OBD runtime status for diagnostics and field recovery. */
        ObdStatusResponse: {
            backoff_active: boolean;
            configured_device_mac: string | null;
            configured_device_name: string | null;
            connected: boolean;
            connection_state: string;
            debug_hint: string | null;
            device_mac: string | null;
            device_name: string | null;
            error_count: number;
            last_error: string | null;
            last_raw_response: string | null;
            last_rpm: number | null;
            last_sample_age_s: number | null;
            last_speed_kmh: number | null;
            paired: boolean;
            poll_mode: string | null;
            reconnect_delay_s: number | null;
            request_rtt_ms: number | null;
            rfcomm_channel: number | null;
            rpm_effective_hz: number | null;
            rpm_sample_age_s: number | null;
            rpm_target_interval_ms: number | null;
            timeout_count: number;
            trusted: boolean;
        };
        OrderCodeValue: "T1" | "T2" | "P1" | "P2" | "E1" | "E2";
        /** One order-tracked finding as a workshop worksheet row. */
        OrderFindingRow: {
            confidence_level: components["schemas"]["ConfidenceLevelValue"];
            finding_id: string;
            frequency_hz: number | null;
            location: string | null;
            order_code: components["schemas"]["OrderCodeValue"];
            phases: string[];
            presence_ratio: number | null;
            reference_speed_kmh: number | null;
            source: string;
            speed_max_kmh: number | null;
            speed_min_kmh: number | null;
        };
        /** Response body for an outlier-summary bucket. */
        OutlierSummaryResponse: {
            count: number;
            lower_bound: number | null;
            outlier_count: number;
            outlier_pct: number;
            upper_bound: number | null;
        };
        PayloadObject: {
            [key: string]: components["schemas"]["JsonSchemaValue"];
        };
        PayloadValue: components["schemas"]["JsonSchemaNestedValue"] | components["schemas"]["JsonSchemaNestedObject"] | ((components["schemas"]["JsonSchemaNestedValue"] | components["schemas"]["JsonSchemaNestedObject"])[]);
        /** Typed HTTP contract for one ranked peak table row. */
        PeakTableRow: {
            burstiness: number;
            frequency_hz: number;
            max_intensity_db: number | null;
            median_intensity_db: number | null;
            median_vs_run_noise_ratio: number;
            order_label: string;
            p95_intensity_db: number | null;
            p95_vs_run_noise_ratio: number;
            peak_classification: string;
            persistence_score: number;
            presence_ratio: number;
            rank: number;
            run_noise_baseline_db: number | null;
            strength_db: number | null;
            strength_floor_db: number | null;
            suspected_source: string;
            typical_speed_band: string;
        };
        /** HTTP contract for optional driving-phase evidence attached to a finding. */
        PhaseEvidence: {
            cruise_fraction?: number | null;
            phases_detected?: string[];
        };
        /** Response body for aggregate driving-phase coverage metrics. */
        PhaseInfoResponse: {
            cruise_pct: number;
            has_acceleration: boolean;
            has_cruise: boolean;
            idle_pct: number;
            phase_counts: {
                [key: string]: number;
            };
            phase_pcts: {
                [key: string]: number;
            };
            segment_count: number;
            speed_unknown_pct: number;
            total_samples: number;
        };
        /** Response body for per-phase intensity aggregates at one location. */
        PhaseIntensityStatsResponse: {
            count: number;
            max_intensity_db: number | null;
            mean_intensity_db: number | null;
        };
        /** Typed HTTP contract for a summarized driving-phase segment. */
        PhaseSegmentSummaryResponse: {
            end_idx: number;
            end_t_s: number | null;
            phase: string;
            sample_count: number;
            speed_max_kmh: number | null;
            speed_min_kmh: number | null;
            start_idx: number;
            start_t_s: number | null;
        };
        /** Typed HTTP contract for one phase-aware speed aggregate row. */
        PhaseSpeedBreakdownRow: {
            count: number;
            max_speed_kmh: number | null;
            max_vibration_strength_db: number | null;
            mean_speed_kmh: number | null;
            mean_vibration_strength_db: number | null;
            phase: string;
        };
        /** Response body for one summarized phase-timeline interval. */
        PhaseTimelineEntryResponse: {
            end_t_s: number | null;
            has_fault_evidence: boolean;
            phase: string;
            speed_max_kmh: number | null;
            speed_min_kmh: number | null;
            start_t_s: number | null;
        };
        /**
         * Typed HTTP contract for the ``plots`` section of a run summary.
         *
         * Only the ranked peak table is produced. Runs persisted by older versions may
         * still carry additional plot series; they are ignored on validation.
         */
        PlotDataResult: {
            peaks_table: components["schemas"]["PeakTableRow"][];
        };
        /** Which order families the active car can test; informational, never blocks capture. */
        RecordingCaptureCapabilitiesResponse: {
            driveline: components["schemas"]["DrivelineCapability"];
            engine: components["schemas"]["EngineCapability"];
            wheel: components["schemas"]["WheelCapability"];
        };
        /** One capture-readiness checklist item returned by the recording status route. */
        RecordingCaptureReadinessCheckResponse: {
            check_key: string;
            details?: {
                [key: string]: number | string;
            };
            reason_key?: string | null;
            state: "pass" | "warn" | "fail";
        };
        /** Backend-owned live capture-readiness summary for idle/pre-record states. */
        RecordingCaptureReadinessResponse: {
            /** `null` without an active car. */
            capabilities?: components["schemas"]["RecordingCaptureCapabilitiesResponse"] | null;
            checks: components["schemas"]["RecordingCaptureReadinessCheckResponse"][];
            is_ready: boolean;
        };
        /** Response body with the current recording (run-logging) status. */
        RecordingStatusResponse: {
            analysis_in_progress: boolean;
            capture_readiness?: components["schemas"]["RecordingCaptureReadinessResponse"] | null;
            /** Seconds the current run has been recording, on the Pi's monotonic clock; right even when the Pi wall clock (and so `start_time_utc`) is wrong. `null` when not recording. */
            elapsed_s?: number | null;
            enabled: boolean;
            /** Firm stops counted so far in the current recording's guided brake step, by the analysis's own braking rule; a stop counts about 3 s after it ends. */
            guided_brake_stops: number;
            /** The guided test-drive step in progress (sweep, hold, coast_down, brake), if any. */
            guided_phase?: components["schemas"]["GuidedPhaseName"] | null;
            /** Guided test-drive steps finished so far in the current recording, in the order first finished; lets the Live page restore the guided panel after a reload. */
            guided_phases_completed?: components["schemas"]["GuidedPhaseName"][];
            last_completed_run_error?: string | null;
            last_completed_run_id?: string | null;
            /** The run most recently stopped since the server started; cleared when a new run starts. Until then `samples_written` and `samples_dropped` describe it. */
            last_run_id?: string | null;
            /** Why the most recent run stopped; cleared when a new run starts. `max_duration` means it hit the 30-minute recording limit. */
            last_stop_reason?: components["schemas"]["RecordingStopReason"] | null;
            run_id: string | null;
            samples_dropped: number;
            samples_written: number;
            start_time_utc?: string | null;
            write_error: string | null;
        };
        RecordingStopReason: "manual" | "restart" | "shutdown" | "no_data_timeout" | "max_duration";
        ReferenceProvenanceValue: "user_confirmed" | "official_exact" | "official_derived" | "reputable_secondary_crosschecked" | "family_default" | "unverified" | "missing";
        /** Response body confirming removal of a disconnected client. */
        RemoveClientResponse: {
            id: string;
            status: string;
        };
        ResolvedSpeedSource: "gps" | "obd2" | "manual" | "fallback_manual" | "none";
        RpmSourceValue: "measured" | "estimated_top_gear" | "none";
        /** Typed HTTP contract for one run-suitability diagnostic check. */
        RunSuitabilityCheck: {
            check_key: string;
            explanation?: components["schemas"]["PayloadValue"];
            state: string;
        };
        /** Response body confirming the new location assignment for a client. */
        SetClientLocationResponse: {
            id: string;
            location_code: string;
            mac_address: string;
            name: string;
        };
        /** Request body for setting the sensor location code. */
        SetLocationRequest: {
            location_code: string;
        };
        /** Whether one source family was the candidate, ruled out, or not testable. */
        SourceCheck: {
            reason: components["schemas"]["SourceCheckReason"] | null;
            source: string;
            status: components["schemas"]["SourceCheckStatus"];
        };
        SourceCheckReason: "no_tire_reference" | "no_drive_reference" | "no_engine_reference" | "manual_speed" | "top_gear_assumed" | "estimated_final_drive" | "estimated_top_gear" | "no_matching_order" | "stayed_in_neutral" | "stopped_in_neutral" | "engine_may_be_off" | "engine_not_running" | "electric_car" | "same_rhythm_as_candidate" | "no_braking" | "only_while_braking" | "regen_braking";
        SourceCheckStatus: "candidate" | "ruled_out" | "ruled_out_estimated" | "not_testable" | "not_applicable";
        /** One recurring spectral peak (0.5 Hz bin) and its median amplitude. */
        SpectrumPeak: {
            amplitude_mg: number;
            hz: number;
        };
        /** Median amplitude of the diagnosed order in one 5 km/h speed bin at one location. */
        SpeedAmplitudePoint: {
            amplitude_mg: number;
            location: string;
            speed_kmh: number;
        };
        /** Typed HTTP contract for one speed-band aggregate row. */
        SpeedBreakdownRow: {
            count: number;
            max_vibration_strength_db: number | null;
            mean_vibration_strength_db: number | null;
            speed_range: string;
        };
        SpeedDependenceValue: "vehicle_speed" | "engine_speed";
        /** How vehicle speed is acquired. */
        SpeedSourceKind: "gps" | "obd2" | "manual";
        /** Request body for configuring the speed source (GPS, manual, OBD2, etc.). */
        SpeedSourceRequest: {
            manual_speed_kph?: number | null;
            obd_device_mac?: string | null;
            obd_device_name?: string | null;
            speed_source?: components["schemas"]["SpeedSourceKind"] | null;
            stale_timeout_s?: number | null;
        };
        /** Response body for the current speed-source configuration. */
        SpeedSourceResponse: {
            manual_speed_kph: number | null;
            obd_device_mac?: string | null;
            obd_device_name?: string | null;
            speed_source: components["schemas"]["SpeedSourceKind"];
            stale_timeout_s: number;
        };
        /** Response body for the live GPS/speed-source connection status. */
        SpeedSourceStatusResponse: {
            connection_state: string;
            device: string | null;
            effective_speed_kmh: number | null;
            epv_m: number | null;
            epx_m: number | null;
            epy_m: number | null;
            fallback_active: boolean;
            fix_dimension: "3d" | "2d" | "none";
            fix_mode: number | null;
            gps_enabled: boolean;
            last_error: string | null;
            last_update_age_s: number | null;
            raw_speed_kmh: number | null;
            reconnect_delay_s: number | null;
            speed_confidence: "low" | "medium" | "high";
            speed_source: components["schemas"]["ResolvedSpeedSource"];
            stale_timeout_s: number;
        };
        /** Response body for one summarized speed-profile snapshot. */
        SpeedStatsResponse: {
            max_kmh: number | null;
            mean_kmh: number | null;
            min_kmh: number | null;
            range_kmh: number | null;
            sample_count: number;
            stddev_kmh: number | null;
            steady_speed: boolean;
        };
        SpeedUnitCode: "kmh" | "mps";
        /** Request body for changing the displayed speed unit. */
        SpeedUnitRequest: {
            speed_unit: components["schemas"]["SpeedUnitCode"];
        };
        /** Response body confirming the active speed unit. */
        SpeedUnitResponse: {
            speed_unit: components["schemas"]["SpeedUnitCode"];
        };
        /** Response body for per-location strength-bucket coverage. */
        StrengthBucketDistributionResponse: {
            counts: {
                [key: string]: number;
            };
            percent_time_l0: number;
            percent_time_l1: number;
            percent_time_l2: number;
            percent_time_l3: number;
            percent_time_l4: number;
            percent_time_l5: number;
            total: number;
        };
        /** Response body for a persisted summary warning before localization. */
        SummaryWarningResponse: {
            applies_to: string;
            code: string;
            detail?: components["schemas"]["PayloadValue"];
            severity: "warn" | "error";
            title: components["schemas"]["PayloadValue"];
        };
        /** Typed HTTP contract for the serialized likely-origin payload. */
        SuspectedVibrationOriginPayload: {
            alternative_locations?: string[];
            dominance_ratio?: number | null;
            dominant_phase?: string | null;
            explanation?: components["schemas"]["PayloadValue"];
            location?: string | null;
            speed_band?: string | null;
            suspected_source?: string | null;
            weak_spatial_separation?: boolean | null;
        };
        /** Reference data the order analysis used, with where each reference came from. */
        TestConditions: {
            drive_layout?: components["schemas"]["DriveLayoutValue"] | null;
            final_drive_axle?: components["schemas"]["FinalDriveAxleValue"] | null;
            final_drive_provenance: components["schemas"]["ReferenceProvenanceValue"];
            final_drive_ratio: number | null;
            fuel_type: components["schemas"]["FuelTypeValue"] | null;
            gear_ratio: number | null;
            gear_ratio_provenance: components["schemas"]["ReferenceProvenanceValue"];
            propshaft?: boolean | null;
            rpm_source: components["schemas"]["RpmSourceValue"];
            speed_source: string | null;
            tire_circumference_m: number | null;
            tire_provenance: components["schemas"]["ReferenceProvenanceValue"];
        };
        TireSpeedAxle: "front" | "rear" | "average";
        /** Response body confirming whether an OTA update job was cancelled. */
        UpdateCancelResponse: {
            cancelled: boolean;
        };
        /** Response body for a single issue raised during an OTA update phase. */
        UpdateIssueResponse: {
            detail: string;
            message: string;
            phase: string;
        };
        /** Response body for updater runtime/build verification details. */
        UpdateRuntimeResponse: {
            assets_verified: boolean;
            commit: string;
            has_packaged_static: boolean;
            static_assets_hash: string;
            static_build_commit: string;
            static_build_source_hash: string;
            ui_source_hash: string;
            version: string;
        };
        /** Request body to start an OTA software update (provides Wi-Fi credentials). */
        UpdateStartRequest: {
            password: string;
            ssid?: string | null;
            transport: components["schemas"]["UpdateTransport"];
        };
        /** Response body confirming that an OTA update job has started. */
        UpdateStartResponse: {
            ssid?: string | null;
            status: string;
            transport: string;
        };
        /** Response body for the full OTA update job status. */
        UpdateStatusResponse: {
            exit_code?: number | null;
            finished_at?: number | null;
            issues: components["schemas"]["UpdateIssueResponse"][];
            last_success_at?: number | null;
            log_tail: string[];
            phase: string;
            phase_elapsed_s?: number | null;
            phase_started_at?: number | null;
            runtime: components["schemas"]["UpdateRuntimeResponse"];
            ssid?: string | null;
            started_at?: number | null;
            state: string;
            transport: string;
            updated_at?: number | null;
            uplink_interface?: string | null;
        };
        /** Network path used by a single OTA update run. */
        UpdateTransport: "wifi" | "usb_internet";
        /** Response body describing the current USB internet detection state. */
        UsbInternetStatusResponse: {
            connection_name?: string | null;
            detected: boolean;
            diagnostic: string;
            driver?: string | null;
            gateway?: string | null;
            has_default_route: boolean;
            interface_name?: string | null;
            ipv4_addresses: string[];
            usable: boolean;
        };
        ValidationError: {
            ctx?: Record<string, never>;
            input?: unknown;
            loc: (string | number)[];
            msg: string;
            type: string;
        };
        WheelCapability: "ok" | "missing_tire" | "manual_speed";
    };
}

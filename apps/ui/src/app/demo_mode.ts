import { defaultLiveAnalysisConfig } from "../constants";
import { EXPECTED_LIVE_PAYLOAD_SCHEMA_VERSION } from "../transport/live_models";
import { composeVehicleSettings, type AppState } from "./ui_app_state";
import { batch } from "./ui_signals";

type DemoDeps = {
  ingestTransportPayload(payload: unknown): void;
  state: Pick<AppState, "settings">;
};

declare global {
  interface Window {
    __vibesensorDemoCleanup?: () => void;
  }
}

export function runDemoMode(deps: DemoDeps): void {
  const { state } = deps;
  const demoSampleRateHz = defaultLiveAnalysisConfig.sampleRateHz;
  const spectrumMaxHz = defaultLiveAnalysisConfig.spectrumMaxHz;

  const demoClients = [
    {
      id: "aabbcc001122",
      name: "Front Left Wheel",
      mac_address: "AA:BB:CC:00:11:22",
      connected: true,
      last_seen_age_ms: 42,
      dropped_frames: 0,
      frames_total: 8400,
      frame_samples: 200,
      location_code: "front_left_wheel",
      firmware_version: "demo-1.0.0",
      sample_rate_hz: demoSampleRateHz,
    },
    {
      id: "aabbcc001133",
      name: "Front Right Wheel",
      mac_address: "AA:BB:CC:00:11:33",
      connected: true,
      last_seen_age_ms: 38,
      dropped_frames: 1,
      frames_total: 8395,
      frame_samples: 200,
      location_code: "front_right_wheel",
      firmware_version: "demo-1.0.0",
      sample_rate_hz: demoSampleRateHz,
    },
    {
      id: "aabbcc001144",
      name: "Rear Left Wheel",
      mac_address: "AA:BB:CC:00:11:44",
      connected: true,
      last_seen_age_ms: 45,
      dropped_frames: 0,
      frames_total: 8388,
      frame_samples: 200,
      location_code: "rear_left_wheel",
      firmware_version: "demo-1.0.0",
      sample_rate_hz: demoSampleRateHz,
    },
    {
      id: "aabbcc001155",
      name: "Rear Right Wheel",
      mac_address: "AA:BB:CC:00:11:55",
      connected: true,
      last_seen_age_ms: 51,
      dropped_frames: 0,
      frames_total: 8401,
      frame_samples: 200,
      location_code: "rear_right_wheel",
      firmware_version: "demo-1.0.0",
      sample_rate_hz: demoSampleRateHz,
    },
    {
      id: "aabbcc001166",
      name: "Engine Bay",
      mac_address: "AA:BB:CC:00:11:66",
      connected: true,
      last_seen_age_ms: 39,
      dropped_frames: 2,
      frames_total: 8390,
      frame_samples: 200,
      location_code: "engine_bay",
      firmware_version: "demo-1.0.0",
      sample_rate_hz: demoSampleRateHz,
    },
  ];

  const freqCount = 256;
  const freqArr = Array.from(
    { length: freqCount },
    (_, i) => (i / freqCount) * spectrumMaxHz,
  );

  function sineSpectrum(
    baseAmps: number[],
    peakHz: number,
    peakAmp: number,
  ): number[] {
    return freqArr.map((hz, i) => {
      const base = baseAmps[i % baseAmps.length] || 0.001;
      const dist = Math.abs(hz - peakHz);
      const peak = dist < 8 ? peakAmp * Math.exp((-dist * dist) / 18) : 0;
      return base + peak;
    });
  }

  const baseNoise: number[] = [];
  let seed = 42;
  for (let i = 0; i < freqCount; i++) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    baseNoise.push(0.0008 + (seed % 100) * 0.00004);
  }

  const demoSpectra: Record<
    string,
    {
      combined_spectrum_amp_g: number[];
      freq: number[];
      strength_metrics: {
        noise_floor_amp_g: number;
        peak_amp_g: number;
        strength_bucket: string | null;
        top_peaks: Array<{
          amp: number;
          hz: number;
          strength_bucket: string | null;
          vibration_strength_db: number;
        }>;
        vibration_strength_db: number;
      };
    }
  > = {};
  const peakConfigs = [
    { hz: 12.3, amp: 0.032, db: 15.1, bucket: "l2" },
    { hz: 12.1, amp: 0.025, db: 14.0, bucket: "l2" },
    { hz: 12.5, amp: 0.018, db: 12.6, bucket: "l2" },
    { hz: 12.2, amp: 0.045, db: 16.5, bucket: "l2" },
    { hz: 36.8, amp: 0.012, db: 10.8, bucket: "l2" },
  ];
  demoClients.forEach((client, idx) => {
    const pk = peakConfigs[idx];
    const combined = sineSpectrum(baseNoise, pk.hz, pk.amp);
    demoSpectra[client.id] = {
      freq: freqArr,
      combined_spectrum_amp_g: combined,
      strength_metrics: {
        vibration_strength_db: pk.db,
        peak_amp_g: pk.amp,
        noise_floor_amp_g: 0.0,
        strength_bucket: pk.bucket,
        top_peaks: [
          {
            hz: pk.hz,
            amp: pk.amp,
            vibration_strength_db: pk.db,
            strength_bucket: pk.bucket,
          },
        ],
      },
    };
  });

  const demoPayload = {
    schema_version: EXPECTED_LIVE_PAYLOAD_SCHEMA_VERSION,
    server_time: new Date().toISOString(),
    clients: demoClients,
    selected_client_id: demoClients[0]?.id ?? null,
    speed_mps: 22.2,
    rotational_speeds: {
      basis_speed_source: "gps",
      wheel: {
        rpm: 738,
        mode: "calculated",
        reason: null,
      },
      driveshaft: {
        rpm: 1476,
        mode: "calculated",
        reason: null,
      },
      engine: {
        rpm: 2208,
        mode: "calculated",
        reason: null,
      },
      order_bands: [
        { key: "wheel_1x", center_hz: 12.3, tolerance: 0.08 },
        { key: "wheel_2x", center_hz: 24.6, tolerance: 0.08 },
        { key: "driveshaft_1x", center_hz: 24.6, tolerance: 0.08 },
        { key: "engine_1x", center_hz: 36.8, tolerance: 0.08 },
      ],
    },
    spectra: { clients: demoSpectra },
  };

  batch(() => {
    state.settings.car.carsLoaded.value = true;
    state.settings.car.cars.value = [
      {
        id: "demo-car-1",
        name: "Demo Hatch",
        type: "Simulated setup",
        variant: "Audit baseline",
        aspects: composeVehicleSettings(
          state.settings.car.activeVehicleSettings.value,
          state.settings.analysis.vehicleSettings.value,
        ),
      },
    ];
    state.settings.car.activeCarId.value = "demo-car-1";
  });
  deps.ingestTransportPayload(demoPayload);

  window.__vibesensorDemoCleanup = undefined;
}

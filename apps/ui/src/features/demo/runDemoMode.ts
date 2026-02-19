import { METRIC_FIELDS } from "../../generated/shared_contracts";

type DemoDeps = {
  state: { wsState: string; hasReceivedPayload: boolean };
  renderWsState: () => void;
  applyPayload: (payload: unknown) => void;
};

declare global {
  interface Window {
    __vibesensorDemoCleanup?: () => void;
  }
}

export function runDemoMode(deps: DemoDeps): void {
  const { state, renderWsState, applyPayload } = deps;

  state.wsState = "connected";
  renderWsState();

  const demoClients = [
    { id: "aabbcc001122", name: "Front Left Wheel", mac_address: "AA:BB:CC:00:11:22", connected: true, last_seen_age_ms: 42, dropped_frames: 0, frames_total: 8400 },
    { id: "aabbcc001133", name: "Front Right Wheel", mac_address: "AA:BB:CC:00:11:33", connected: true, last_seen_age_ms: 38, dropped_frames: 1, frames_total: 8395 },
    { id: "aabbcc001144", name: "Rear Left Wheel", mac_address: "AA:BB:CC:00:11:44", connected: true, last_seen_age_ms: 45, dropped_frames: 0, frames_total: 8388 },
    { id: "aabbcc001155", name: "Rear Right Wheel", mac_address: "AA:BB:CC:00:11:55", connected: true, last_seen_age_ms: 51, dropped_frames: 0, frames_total: 8401 },
    { id: "aabbcc001166", name: "Engine Bay", mac_address: "AA:BB:CC:00:11:66", connected: true, last_seen_age_ms: 39, dropped_frames: 2, frames_total: 8390 },
  ];

  const freqCount = 256;
  const freqArr: number[] = [];
  for (let i = 0; i < freqCount; i++) freqArr.push((i / freqCount) * 250);

  function sineSpectrum(baseAmps: number[], peakHz: number, peakAmp: number): number[] {
    return freqArr.map((hz, i) => {
      const base = baseAmps[i % baseAmps.length] || 0.001;
      const dist = Math.abs(hz - peakHz);
      const peak = dist < 8 ? peakAmp * Math.exp(-dist * dist / 18) : 0;
      return base + peak;
    });
  }

  const baseNoise: number[] = [];
  let seed = 42;
  for (let i = 0; i < freqCount; i++) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    baseNoise.push(0.0008 + (seed % 100) * 0.00004);
  }

  const demoSpectra: Record<string, unknown> = {};
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
        [METRIC_FIELDS.vibration_strength_db]: pk.db,
        [METRIC_FIELDS.strength_bucket]: pk.bucket,
      },
    };
  });

  const demoStrengthBands = [
    { key: "l1", min_db: 0 },
    { key: "l2", min_db: 10 },
    { key: "l3", min_db: 18 },
    { key: "l4", min_db: 28 },
    { key: "l5", min_db: 40 },
  ];

  const demoPayload = {
    server_time: new Date().toISOString(),
    clients: demoClients,
    speed_mps: 22.2,
    spectra: { clients: demoSpectra },
    diagnostics: {
      strength_bands: demoStrengthBands,
      matrix: null,
      events: [],
      levels: { by_source: { wheel: 14.2, driveshaft: 8.1, engine: 6.5, other: 3.2 } },
    },
  };

  state.hasReceivedPayload = true;
  applyPayload(demoPayload);

  const demoEventTimeout = setTimeout(() => {
    const eventPayload = {
      ...demoPayload,
      diagnostics: {
        ...demoPayload.diagnostics,
        events: [
          {
            severity_key: "l3",
            [METRIC_FIELDS.vibration_strength_db]: 22.5,
            peak_hz: 12.2,
            class_key: "wheel",
            sensor_labels: ["Rear Right Wheel"],
          },
        ],
      },
    };
    applyPayload(eventPayload);
  }, 800);

  window.__vibesensorDemoCleanup = () => clearTimeout(demoEventTimeout);
}

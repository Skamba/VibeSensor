import { describe, expect, test } from "vitest";
import { createAppState, applyLivePayloadUpdate } from "../src/app/ui_app_state";
import type { AdaptedPayload } from "../src/transport/live_models";

function makeAdaptedPayload(overrides: Partial<AdaptedPayload> = {}): AdaptedPayload {
  return {
    clients: [],
    speed_mps: 10,
    rotational_speeds: null,
    spectra: null,
    ...overrides,
  };
}

function makeClient(id: string) {
  return {
    id,
    name: `Sensor ${id}`,
    connected: true,
    mac_address: `00:11:22:33:44:${id.slice(-2).padStart(2, "0")}`,
    location_code: "",
    last_seen_age_ms: 0,
    dropped_frames: 0,
    frames_total: 1,
    sample_rate_hz: 1600,
    firmware_version: "1.0.0",
  };
}

describe("applyLivePayloadUpdate", () => {
  test("applies client, speed, spectrum, and selection changes and reports side-effect decisions", () => {
    const state = createAppState();

    const update = applyLivePayloadUpdate({
      realtime: state.realtime,
      spectrum: state.spectrum,
      adaptedPayload: makeAdaptedPayload({
        clients: [makeClient("client-1")],
        speed_mps: 12,
        spectra: {
          clients: {
            "client-1": {
              freq: [10, 20, 30],
              combined: [0.1, 0.2, 0.15],
              strength_metrics: {
                vibration_strength_db: 12,
                peak_amp_g: 0,
                noise_floor_amp_g: 0,
                strength_bucket: null,
                top_peaks: [],
              },
            },
          },
        },
      }),
    });

    expect(state.realtime.clients.value.map((client) => client.id)).toEqual(["client-1"]);
    expect(state.realtime.selectedClientId.value).toBe("client-1");
    expect(state.realtime.speedMps.value).toBe(12);
    expect(state.spectrum.spectra.value.clients["client-1"]?.freq).toEqual([10, 20, 30]);
    expect(state.spectrum.hasSpectrumData.value).toBe(true);
    expect(update.hasSelectedClientChanged).toBe(true);
    expect(update.hasNewSpectrumFrame).toBe(true);
    expect(update.selectedClient?.id).toBe("client-1");
  });

  test("preserves the previous spectrum frame when the adapted payload omits spectra", () => {
    const state = createAppState();
    state.realtime.selectedClientId.value = "client-1";
    state.spectrum.spectra.value = {
      clients: {
        "client-1": {
          freq: [1, 2, 3],
          combined: [0.01, 0.02, 0.03],
          strength_metrics: {
            vibration_strength_db: 5,
            peak_amp_g: 0,
            noise_floor_amp_g: 0,
            strength_bucket: null,
            top_peaks: [],
          },
        },
      },
    };
    state.spectrum.hasSpectrumData.value = true;

    const update = applyLivePayloadUpdate({
      realtime: state.realtime,
      spectrum: state.spectrum,
      adaptedPayload: makeAdaptedPayload({
        clients: [makeClient("client-1")],
        speed_mps: 14,
        spectra: null,
      }),
    });

    expect(state.spectrum.spectra.value.clients["client-1"]?.freq).toEqual([1, 2, 3]);
    expect(state.spectrum.hasSpectrumData.value).toBe(true);
    expect(state.realtime.speedMps.value).toBe(14);
    expect(update.hasSelectedClientChanged).toBe(false);
    expect(update.hasNewSpectrumFrame).toBe(false);
    expect(update.selectedClient?.id).toBe("client-1");
  });

  test("preserves the previous spectrum frame when the heavy payload is unchanged", () => {
    const state = createAppState();
    const previousSpectra = {
      clients: {
        "client-1": {
          freq: [1, 2, 3],
          combined: [0.01, 0.02, 0.03],
          strength_metrics: {
            vibration_strength_db: 5,
            peak_amp_g: 0,
            noise_floor_amp_g: 0,
            strength_bucket: null,
            top_peaks: [{ amp: 0.03, hz: 3, strength_bucket: null, vibration_strength_db: 5 }],
          },
        },
      },
    };
    state.spectrum.spectra.value = previousSpectra;
    state.spectrum.hasSpectrumData.value = true;

    const update = applyLivePayloadUpdate({
      realtime: state.realtime,
      spectrum: state.spectrum,
      adaptedPayload: makeAdaptedPayload({
        clients: [makeClient("client-1")],
        spectra: {
          clients: {
            "client-1": {
              freq: [1, 2, 3],
              combined: [0.01, 0.02, 0.03],
              strength_metrics: {
                vibration_strength_db: 5,
                peak_amp_g: 0,
                noise_floor_amp_g: 0,
                strength_bucket: null,
                top_peaks: [{ amp: 0.03, hz: 3, strength_bucket: null, vibration_strength_db: 5 }],
              },
            },
          },
        },
      }),
    });

    expect(state.spectrum.spectra.value).toBe(previousSpectra);
    expect(update.hasNewSpectrumFrame).toBe(false);
  });
});

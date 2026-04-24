import { describe, expect, test } from "vitest";
import { validateLiveWsPayload } from "../src/ws_payload_validator";

const basePayload = {
  schema_version: "1",
  server_time: "2026-01-01T00:00:00Z",
  clients: [
    {
      id: "sensor-1",
      mac_address: "aa:bb:cc:dd:ee:ff",
      name: "Front Left",
      connected: true,
      location_code: "front_left",
      firmware_version: "1.2.3",
      sample_rate_hz: 800,
      last_seen_age_ms: 0,
      frames_total: 10,
      frame_samples: 1024,
      dropped_frames: 0,
    },
  ],
  selected_client_id: null,
  rotational_speeds: null,
  speed_mps: 12.5,
} as const;

function makeStrengthMetrics() {
  return {
    vibration_strength_db: 12,
    peak_amp_g: 0.12,
    noise_floor_amp_g: 0.01,
    strength_bucket: null,
    top_peaks: [
      {
        hz: 120,
        amp: 0.04,
        vibration_strength_db: 12,
        strength_bucket: null,
      },
    ],
  };
}

describe("validateLiveWsPayload", () => {
  test("accepts a schema-valid payload", () => {
    expect(
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          frame_fingerprint: "sensor-1:0:0:1",
          freq: [10, 20, 30],
          clients: {
            "sensor-1": {
              combined_spectrum_amp_g: [0.1, 0.2, 0.3],
              strength_metrics: makeStrengthMetrics(),
            },
          },
        },
      }),
    ).toMatchObject({
      schema_version: "1",
      clients: [{ id: "sensor-1" }],
      spectra: { frame_fingerprint: "sensor-1:0:0:1" },
    });
  });

  test("reports the failing client-row path", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        clients: [
          {
            ...basePayload.clients[0],
            frames_total: "10",
          },
        ],
      }),
    ).toThrow(/Invalid websocket payload: \/clients\/0\/frames_total/);
  });

  test("reports malformed shared spectrum arrays", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          freq: [10, "bad", 30],
        },
      }),
    ).toThrow(/Invalid websocket payload: \/spectra\/freq/);
  });

  test("reports malformed strength peak fields through Valibot", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          clients: {
            "sensor-1": {
              combined_spectrum_amp_g: [0.1, 0.2, 0.3],
              strength_metrics: {
                ...makeStrengthMetrics(),
                top_peaks: [
                  {
                    hz: 120,
                    amp: "bad",
                    vibration_strength_db: 12,
                    strength_bucket: null,
                  },
                ],
              },
            },
          },
        },
      }),
    ).toThrow(/Invalid websocket payload: \/spectra\/clients\/sensor-1\/strength_metrics\/top_peaks\/0\/amp/);
  });

  test("reports malformed rotational-speed metadata", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        rotational_speeds: {
          basis_speed_source: null,
          wheel: { rpm: 10, mode: null, reason: null },
          driveshaft: { rpm: 20, mode: null, reason: null },
          engine: { rpm: 30, mode: null, reason: null },
          order_bands: [
            {
              key: "1x",
              center_hz: 40,
              tolerance: "wide",
            },
          ],
        },
      }),
    ).toThrow(/Invalid websocket payload: \/rotational_speeds\/order_bands\/0\/tolerance/);
  });

  test("reports malformed spectrum frame fingerprint", () => {
    expect(() =>
      validateLiveWsPayload({
        ...basePayload,
        spectra: {
          frame_fingerprint: 123,
        },
      }),
    ).toThrow(/Invalid websocket payload: \/spectra\/frame_fingerprint/);
  });
});

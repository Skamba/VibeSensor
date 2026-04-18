/**
 * Tests for WS payload contract (schema_version) and shared-freq optimization.
 *
 * Validates:
 *  1. adaptServerPayload uses shared top-level freq when per-client freq is absent
 *  2. adaptServerPayload prefers per-client freq when present (mismatch case)
 *  3. adaptServerPayload rejects payloads that omit required top-level fields
 *  4. EXPECTED_SCHEMA_VERSION matches the server's current version
 */

import { expect, test } from "@playwright/test";
import { adaptServerPayload } from "../src/server_payload";
import { EXPECTED_SCHEMA_VERSION, type StrengthMetricsPayload } from "../src/contracts/ws_payload_types";

function makeStrengthMetrics(
  overrides: Partial<StrengthMetricsPayload> = {},
): StrengthMetricsPayload {
  return {
    vibration_strength_db: 0,
    peak_amp_g: 0,
    noise_floor_amp_g: 0,
    strength_bucket: null,
    top_peaks: [],
    ...overrides,
  };
}

const basePayload = {
  schema_version: EXPECTED_SCHEMA_VERSION,
  server_time: "2026-01-01T00:00:00Z",
  clients: [],
  selected_client_id: null,
  rotational_speeds: null,
  speed_mps: 10,
};

function expectInvalidPayload(payload: unknown): void {
  expect(() => adaptServerPayload(payload)).toThrow(/Invalid websocket payload/);
}

function requireSpectra(adapted: ReturnType<typeof adaptServerPayload>) {
  expect(adapted.spectra).not.toBeNull();
  if (!adapted.spectra) throw new Error("Expected adapted spectra");
  return adapted.spectra;
}

// ---------------------------------------------------------------------------
// Schema version handling
// ---------------------------------------------------------------------------
test.describe("schema_version handling", () => {
  test("accepts matching schema_version without error", () => {
    const adapted = adaptServerPayload({ ...basePayload });
    expect(adapted).toBeDefined();
    expect(adapted.speed_mps).toBe(10);
  });

  test("rejects payload without schema_version", () => {
    const { schema_version: _, ...noVersion } = basePayload;
    expectInvalidPayload(noVersion);
  });

  test("accepts unknown schema_version (logs warning, does not throw)", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      schema_version: "999",
    });
    expect(adapted).toBeDefined();
  });

  test("rejects invalid field types via AJV validation", () => {
    expectInvalidPayload({
      ...basePayload,
      speed_mps: "10",
    });
  });

  test("rejects partial strength_metrics instead of defaulting missing fields", () => {
    expectInvalidPayload({
      ...basePayload,
      spectra: {
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: { vibration_strength_db: 12 },
          },
        },
      },
    });
  });

  test("EXPECTED_SCHEMA_VERSION is string '1'", () => {
    expect(EXPECTED_SCHEMA_VERSION).toBe("1");
  });
});

// ---------------------------------------------------------------------------
// Shared freq optimization (Part A1)
// ---------------------------------------------------------------------------
test.describe("shared freq optimization", () => {
  test("uses shared top-level freq when per-client freq is absent", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
          sensor2: {
            combined_spectrum_amp_g: [0.04, 0.05, 0.06],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 8 }),
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);
    expect(spectra.clients.sensor1.freq).toEqual([10, 20, 30]);
    expect(spectra.clients.sensor2.freq).toEqual([10, 20, 30]);
    expect(spectra.clients.sensor1.strength_metrics.peak_amp_g).toBe(0);
    expect(spectra.clients.sensor1.strength_metrics.noise_floor_amp_g).toBe(0);
    expect(spectra.clients.sensor1.strength_metrics.top_peaks).toEqual([]);
  });

  test("prefers per-client freq over shared when both present", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            freq: [15, 25, 35],
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);
    // Per-client freq takes precedence
    expect(spectra.clients.sensor1.freq).toEqual([15, 25, 35]);
  });

  test("still works with old-style per-client freq (no shared)", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [],
        clients: {
          sensor1: {
            freq: [10, 20, 30],
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);
    expect(spectra.clients.sensor1.freq).toEqual([10, 20, 30]);
  });

  test("skips client when neither shared nor per-client freq available", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
        },
      },
    });
    // No freq at all → client should be skipped
    const spectra = requireSpectra(adapted);
    expect(Object.keys(spectra.clients)).toHaveLength(0);
  });

  test("rejects malformed per-client freq elements instead of skipping the client", () => {
    expectInvalidPayload({
      ...basePayload,
      spectra: {
        clients: {
          sensor1: {
            freq: [10, "bad", 30],
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
        },
      },
    });
  });

  test("skips client when freq and amplitude bin counts differ", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        clients: {
          sensor1: {
            freq: [10, 20],
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);
    expect(Object.keys(spectra.clients)).toHaveLength(0);
  });

  test("handles mixed: some clients with per-client freq, some without", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 12 }),
          },
          sensor2: {
            freq: [15, 25, 35],
            combined_spectrum_amp_g: [0.04, 0.05, 0.06],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 8 }),
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);
    // sensor1 uses shared freq
    expect(spectra.clients.sensor1.freq).toEqual([10, 20, 30]);
    // sensor2 uses its own per-client freq
    expect(spectra.clients.sensor2.freq).toEqual([15, 25, 35]);
  });

  test("rejects malformed strength metric peaks instead of dropping them", () => {
    expectInvalidPayload({
      ...basePayload,
      spectra: {
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: {
              vibration_strength_db: 12,
              peak_amp_g: 0.2,
              noise_floor_amp_g: 0.01,
              strength_bucket: null,
              top_peaks: [
                { hz: 10, amp: 0.1, vibration_strength_db: 12, strength_bucket: "l2" },
                { hz: 20, amp: 0.2 },
              ],
            },
          },
        },
      },
    });
  });

  test("reuses validated client and rotational speed references in hot path", () => {
    const client = {
      id: "sensor1",
      name: "Front Left",
      connected: true,
      mac_address: "001122334455",
      location_code: "front_left_wheel",
      last_seen_age_ms: 5,
      dropped_frames: 0,
      frames_total: 100,
      frame_samples: 512,
      sample_rate_hz: 1600,
      firmware_version: "fw-1.0.0",
    };
    const rotationalSpeeds = {
      basis_speed_source: "gps",
      wheel: { rpm: 738, mode: "calculated", reason: null },
      driveshaft: { rpm: 1476, mode: "calculated", reason: null },
      engine: { rpm: 2208, mode: "calculated", reason: null },
      order_bands: [
        { key: "wheel_1x", center_hz: 12.3, tolerance: 0.08 },
      ],
    };

    const adapted = adaptServerPayload({
      ...basePayload,
      clients: [client],
      rotational_speeds: rotationalSpeeds,
    });

    expect(adapted.clients).toHaveLength(1);
    expect(adapted.clients[0]).toBe(client);
    expect(adapted.rotational_speeds).toBe(rotationalSpeeds);
  });

  test("reuses shared frequency and strength metric references for accepted spectra", () => {
    const sharedFreq = [10, 20, 30];
    const strengthMetrics = makeStrengthMetrics({ vibration_strength_db: 12 });

    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: sharedFreq,
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: strengthMetrics,
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);

    expect(spectra.clients.sensor1.freq).toBe(sharedFreq);
    expect(spectra.clients.sensor1.strength_metrics).toBe(strengthMetrics);
  });
});

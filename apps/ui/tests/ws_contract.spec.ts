/**
 * Tests for WS payload contract (schema_version) and shared-freq optimization.
 *
 * Validates:
 *  1. adaptServerPayload uses shared top-level freq when per-client freq is absent
 *  2. adaptServerPayload prefers per-client freq when present (mismatch case)
 *  3. adaptServerPayload rejects missing schema version and warns on mismatches
 *  4. EXPECTED_SCHEMA_VERSION matches the server's current version
 */

import { afterEach, describe, expect, test, vi } from "vitest";
import {
  EXPECTED_SCHEMA_VERSION,
  type StrengthMetricsPayload,
  type WsClientInfo,
} from "../src/contracts/ws_payload_types";
import type { components as HttpComponents } from "../src/generated/http_api_contracts";
import { adaptServerPayload } from "../src/server_payload";

// Compile-time guard: if `frame_samples` ever regresses to optional in either
// generated contract, this file fails `tsc` before runtime tests run. Keeps
// #3000 closed for good — matches schema `required` list.
type RequiredKeys<T> = {
  [K in keyof T]-?: object extends Pick<T, K> ? never : K;
}[keyof T];

type _WsFrameSamplesRequired =
  "frame_samples" extends RequiredKeys<WsClientInfo> ? true : never;
type _HttpFrameSamplesRequired =
  "frame_samples" extends RequiredKeys<
    HttpComponents["schemas"]["ClientApiRow"]
  >
    ? true
    : never;
const _wsFrameSamplesRequired: _WsFrameSamplesRequired = true;
const _httpFrameSamplesRequired: _HttpFrameSamplesRequired = true;
void _wsFrameSamplesRequired;
void _httpFrameSamplesRequired;

afterEach(() => {
  vi.restoreAllMocks();
});

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
  expect(() => adaptServerPayload(payload)).toThrow(
    /Invalid websocket payload/,
  );
}

async function loadFreshServerPayloadModule(): Promise<{
  adaptServerPayload: typeof import("../src/server_payload").adaptServerPayload;
  uiLogger: typeof import("../src/ui_logger").uiLogger;
}> {
  vi.resetModules();
  const { uiLogger } = await import("../src/ui_logger");
  const { adaptServerPayload } = await import("../src/server_payload");
  return { adaptServerPayload, uiLogger };
}

function requireSpectra(adapted: ReturnType<typeof adaptServerPayload>) {
  expect(adapted.spectra).not.toBeNull();
  if (!adapted.spectra) throw new Error("Expected adapted spectra");
  return adapted.spectra;
}

// ---------------------------------------------------------------------------
// Schema version handling
// ---------------------------------------------------------------------------
describe("schema_version handling", () => {
  test("accepts matching schema_version without error", () => {
    const adapted = adaptServerPayload({ ...basePayload });
    expect(adapted).toBeDefined();
    expect(adapted.speed_mps).toBe(10);
  });

  test("rejects payload without schema_version", () => {
    const { schema_version: _, ...noVersion } = basePayload;
    expectInvalidPayload(noVersion);
  });

  test("accepts unknown schema_version (logs warning, does not throw)", async () => {
    const { adaptServerPayload, uiLogger } =
      await loadFreshServerPayloadModule();
    const errorSpy = vi
      .spyOn(uiLogger, "error")
      .mockImplementation(() => undefined);

    const adapted = adaptServerPayload({
      ...basePayload,
      schema_version: "999",
    });

    expect(adapted).toBeDefined();
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  test("logs unknown schema_version once across repeated mismatches", async () => {
    const { adaptServerPayload, uiLogger } =
      await loadFreshServerPayloadModule();
    const errorSpy = vi
      .spyOn(uiLogger, "error")
      .mockImplementation(() => undefined);

    adaptServerPayload({
      ...basePayload,
      schema_version: "999",
    });
    adaptServerPayload({
      ...basePayload,
      schema_version: "999",
      server_time: "2026-01-01T00:00:01Z",
    });

    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  test("EXPECTED_SCHEMA_VERSION is string '1'", () => {
    expect(EXPECTED_SCHEMA_VERSION).toBe("1");
  });
});

// ---------------------------------------------------------------------------
// Shared freq optimization (Part A1)
// ---------------------------------------------------------------------------
describe("shared freq optimization", () => {
  test("uses shared top-level freq when per-client freq is absent", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        frame_fingerprint: "sensor1:0:0:1|sensor2:1:0:2",
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({
              vibration_strength_db: 12,
            }),
          },
          sensor2: {
            combined_spectrum_amp_g: [0.04, 0.05, 0.06],
            strength_metrics: makeStrengthMetrics({ vibration_strength_db: 8 }),
          },
        },
      },
    });
    const spectra = requireSpectra(adapted);
    expect(spectra.frame_fingerprint).toBe("sensor1:0:0:1|sensor2:1:0:2");
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
            strength_metrics: makeStrengthMetrics({
              vibration_strength_db: 12,
            }),
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
            strength_metrics: makeStrengthMetrics({
              vibration_strength_db: 12,
            }),
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
            strength_metrics: makeStrengthMetrics({
              vibration_strength_db: 12,
            }),
          },
        },
      },
    });
    // No freq at all → client should be skipped
    const spectra = requireSpectra(adapted);
    expect(Object.keys(spectra.clients)).toHaveLength(0);
  });

  test("skips client when freq and amplitude bin counts differ", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        clients: {
          sensor1: {
            freq: [10, 20],
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: makeStrengthMetrics({
              vibration_strength_db: 12,
            }),
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
            strength_metrics: makeStrengthMetrics({
              vibration_strength_db: 12,
            }),
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
      order_bands: [{ key: "wheel_1x", center_hz: 12.3, tolerance: 0.08 }],
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

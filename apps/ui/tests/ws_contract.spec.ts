/**
 * Tests for WS payload contract (schema_version) and shared-freq optimization.
 *
 * Validates:
 *  1. adaptServerPayload uses shared top-level freq when per-client freq is absent
 *  2. adaptServerPayload prefers per-client freq when present (mismatch case)
 *  3. adaptServerPayload accepts schema_version without throwing
 *  4. EXPECTED_SCHEMA_VERSION matches the server's current version
 */

import { expect, test } from "@playwright/test";
import { adaptServerPayload } from "../src/server_payload";
import { EXPECTED_SCHEMA_VERSION } from "../src/contracts/ws_payload_types";

const basePayload: Record<string, unknown> = {
  schema_version: EXPECTED_SCHEMA_VERSION,
  clients: [],
  speed_mps: 10,
  diagnostics: { strength_bands: [], events: [], levels: {} },
};

// ---------------------------------------------------------------------------
// Schema version handling
// ---------------------------------------------------------------------------
test.describe("schema_version handling", () => {
  test("accepts matching schema_version without error", () => {
    const adapted = adaptServerPayload({ ...basePayload });
    expect(adapted).toBeDefined();
    expect(adapted.speed_mps).toBe(10);
  });

  test("accepts payload without schema_version (backwards compat)", () => {
    const { schema_version: _, ...noVersion } = basePayload;
    const adapted = adaptServerPayload(noVersion as Record<string, unknown>);
    expect(adapted).toBeDefined();
  });

  test("accepts unknown schema_version (logs warning, does not throw)", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      schema_version: "999",
    });
    expect(adapted).toBeDefined();
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
            strength_metrics: { vibration_strength_db: 12 },
          },
          sensor2: {
            combined_spectrum_amp_g: [0.04, 0.05, 0.06],
            strength_metrics: { vibration_strength_db: 8 },
          },
        },
      },
    });
    expect(adapted.spectra).not.toBeNull();
    expect(adapted.spectra!.clients.sensor1.freq).toEqual([10, 20, 30]);
    expect(adapted.spectra!.clients.sensor2.freq).toEqual([10, 20, 30]);
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
            strength_metrics: { vibration_strength_db: 12 },
          },
        },
      },
    });
    expect(adapted.spectra).not.toBeNull();
    // Per-client freq takes precedence
    expect(adapted.spectra!.clients.sensor1.freq).toEqual([15, 25, 35]);
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
            strength_metrics: { vibration_strength_db: 12 },
          },
        },
      },
    });
    expect(adapted.spectra).not.toBeNull();
    expect(adapted.spectra!.clients.sensor1.freq).toEqual([10, 20, 30]);
  });

  test("skips client when neither shared nor per-client freq available", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: { vibration_strength_db: 12 },
          },
        },
      },
    });
    // No freq at all → client should be skipped
    expect(adapted.spectra).not.toBeNull();
    expect(Object.keys(adapted.spectra!.clients)).toHaveLength(0);
  });

  test("handles mixed: some clients with per-client freq, some without", () => {
    const adapted = adaptServerPayload({
      ...basePayload,
      spectra: {
        freq: [10, 20, 30],
        clients: {
          sensor1: {
            combined_spectrum_amp_g: [0.01, 0.02, 0.03],
            strength_metrics: { vibration_strength_db: 12 },
          },
          sensor2: {
            freq: [15, 25, 35],
            combined_spectrum_amp_g: [0.04, 0.05, 0.06],
            strength_metrics: { vibration_strength_db: 8 },
          },
        },
      },
    });
    expect(adapted.spectra).not.toBeNull();
    // sensor1 uses shared freq
    expect(adapted.spectra!.clients.sensor1.freq).toEqual([10, 20, 30]);
    // sensor2 uses its own per-client freq
    expect(adapted.spectra!.clients.sensor2.freq).toEqual([15, 25, 35]);
  });
});

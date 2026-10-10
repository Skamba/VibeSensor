import { describe, expect, test } from "vitest";

import { defaultLiveAnalysisConfig } from "../src/constants";
import { demoPayload } from "../src/demo";
import { clients, selectedClientId, syncSelection } from "../src/live_store";
import { createSelectionSender, mergeSpectra } from "../src/live_sync";
import { adaptServerPayload } from "../src/server_payload";
import type {
  AdaptedClient,
  SpectrumFrameData,
} from "../src/transport/live_models";

function frame(db: number, fingerprint?: string): SpectrumFrameData {
  return {
    ...(fingerprint ? { frame_fingerprint: fingerprint } : {}),
    clients: {
      s1: {
        freq: [1, 2, 3],
        combined: [0.01, 0.02, 0.03],
        peak_mg: 112,
        strength_metrics: {
          vibration_strength_db: db,
          peak_amp_g: 0,
          noise_floor_amp_g: 0,
          strength_bucket: null,
          top_peaks: [
            {
              amp: 0.03,
              hz: 3,
              strength_bucket: null,
              vibration_strength_db: db,
            },
          ],
        },
      },
    },
  };
}

describe("mergeSpectra", () => {
  test("keeps the previous frame when a payload has no spectra or the same frame", () => {
    const previous = frame(5);
    expect(mergeSpectra(previous, null)).toBe(previous);
    expect(mergeSpectra(previous, frame(5))).toBe(previous);
    const changed = frame(6);
    expect(mergeSpectra(previous, changed)).toBe(changed);
  });

  test("compares fingerprints instead of contents when both frames have one", () => {
    const previous = frame(5, "f1");
    expect(mergeSpectra(previous, frame(9, "f1"))).toBe(previous);
    const next = frame(5, "f2");
    expect(mergeSpectra(previous, next)).toBe(next);
  });
});

describe("selection sync", () => {
  test("sends the selection once per connection and on every change while connected", () => {
    const sent: Array<string | null> = [];
    const update = createSelectionSender((id) => sent.push(id));
    update(false, "a");
    expect(sent).toEqual([]);
    update(true, "a");
    update(true, "a");
    expect(sent).toEqual(["a"]);
    update(true, "b");
    expect(sent).toEqual(["a", "b"]);
    update(false, "b");
    update(true, "b");
    expect(sent).toEqual(["a", "b", "b"]);
  });

  test("selects the first connected sensor and replaces a selection that disappeared", () => {
    const sensor = (id: string, connected: boolean) =>
      ({ id, connected }) as AdaptedClient;
    clients.value = [sensor("off", false), sensor("on", true)];
    selectedClientId.value = null;
    syncSelection();
    expect(selectedClientId.value).toBe("on");
    clients.value = [sensor("off", false)];
    syncSelection();
    expect(selectedClientId.value).toBe("off");
    clients.value = [];
    syncSelection();
    expect(selectedClientId.value).toBeNull();
  });
});

test("the demo payload is a valid live payload with five sensors", () => {
  const adapted = adaptServerPayload(demoPayload());
  expect(adapted.clients).toHaveLength(5);
  expect(
    adapted.clients.every(
      (client) =>
        client.sample_rate_hz === defaultLiveAnalysisConfig.sampleRateHz,
    ),
  ).toBe(true);
  expect(
    adapted.spectra?.clients.aabbcc001122?.strength_metrics
      .vibration_strength_db,
  ).toEqual(expect.any(Number));
  expect(adapted.rotational_speeds?.order_bands).toHaveLength(4);
});

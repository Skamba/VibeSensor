import { describe, expect, test } from "vitest";

import {
  activeFrequency,
  bandsAt,
  createInspectorFeed,
  focusEntry,
  type InspectorInput,
  inspectorText,
  legendModel,
  orderBands,
  overlayMessage,
  type OverlayInput,
  type SensorLevels,
  type SeriesEntry,
} from "../src/pages/spectrum/spectrum_model";

const t = (key: string, vars?: Record<string, unknown>) =>
  vars && Object.keys(vars).length ? `${key}:${JSON.stringify(vars)}` : key;

const entries: SeriesEntry[] = [
  { id: "a", label: "Front", color: "red", values: [5, 12, 3, 1] },
  { id: "b", label: "Rear", color: "blue", values: [2, 4, 8, 6] },
];
const freqAxis = [10, 20, 30, 40];
const levels: SensorLevels = {
  strengthDb: (id) => ({ a: 12, b: 8 })[id] ?? null,
  topPeakHz: (id) => ({ a: 19, b: 31 })[id] ?? null,
};
const bands = orderBands(
  {
    basis_speed_source: null,
    wheel: { rpm: 600, mode: null, reason: null },
    driveshaft: { rpm: null, mode: null, reason: null },
    engine: { rpm: null, mode: null, reason: null },
    order_bands: [
      { key: "wheel_1x", center_hz: 20, tolerance: 0.1 },
      { key: "engine_1x", center_hz: 30, tolerance: 0.1 },
      { key: "broken", center_hz: 0, tolerance: 0.1 },
    ],
  },
  t,
);

function input(overrides: Partial<InspectorInput> = {}): InspectorInput {
  return {
    entries,
    freqAxis,
    bands,
    pinnedId: null,
    cursorIdx: null,
    levels,
    ...overrides,
  };
}

describe("order bands", () => {
  test("turns valid server bands into labelled frequency ranges", () => {
    expect(bands.map((band) => [band.label, band.min_hz, band.max_hz])).toEqual(
      [
        ["bands.wheel_1x", 18, 22],
        ["bands.engine_1x", 27, 33],
      ],
    );
    expect(orderBands(null, t)).toEqual([]);
  });

  test("the band legend lists the bands at the inspected frequency", () => {
    expect(activeFrequency(input())).toBe(20);
    expect(bandsAt(bands, 20).map((band) => band.label)).toEqual([
      "bands.wheel_1x",
    ]);
    expect(activeFrequency(input({ cursorIdx: 2 }))).toBe(30);
    expect(activeFrequency(input({ pinnedId: "b" }))).toBe(30);
    expect(bandsAt(bands, 40)).toEqual([]);
  });
});

describe("trace focus", () => {
  test("focuses the pinned trace, else the loudest", () => {
    expect(focusEntry(entries, null, levels)?.id).toBe("a");
    expect(focusEntry(entries, "b", levels)?.id).toBe("b");
    expect(focusEntry(entries, "gone", levels)?.id).toBe("a");
  });

  test("legend chips show each level and which trace is isolated", () => {
    const all = legendModel(entries, null, levels, t);
    expect(all?.allActive).toBe(true);
    expect(all?.items.map((item) => [item.detail, item.state])).toEqual([
      ['spectrum.legend.sensor_level:{"value":"12.0"}', undefined],
      ['spectrum.legend.sensor_level:{"value":"8.0"}', undefined],
    ]);
    const pinned = legendModel(entries, "a", levels, t);
    expect(pinned?.allActive).toBe(false);
    expect(pinned?.items.map((item) => item.state)).toEqual([
      "active",
      "muted",
    ]);
    expect(pinned?.items[0]?.title).toBe("spectrum.legend.clear_focus");
    expect(pinned?.items[1]?.ariaLabel).toBe(
      'Rear. spectrum.legend.state_inactive. spectrum.legend.sensor_level:{"value":"8.0"}',
    );
    const noLevels = legendModel(
      entries,
      null,
      { strengthDb: () => null, topPeakHz: () => null },
      t,
    );
    expect(noLevels?.items[0]?.detail).toBe("spectrum.legend.state_visible");
    expect(legendModel([], null, levels, t)).toBeNull();
  });
});

describe("inspector", () => {
  test("describes the hovered bin, else the focused peak, else a hint", () => {
    expect(inspectorText(input({ cursorIdx: 2 }), t)).toEqual({
      mode: "hover",
      text: 'spectrum.inspector_hover:{"sensor":"Front","freq":"30.0","value":"3.0","bands":"bands.engine_1x"}',
    });
    expect(inspectorText(input(), t)).toEqual({
      mode: "focus",
      text: 'spectrum.inspector_focus_strongest:{"sensor":"Front","freq":"20.0","value":"12.0","bands":"bands.wheel_1x"}',
    });
    expect(inspectorText(input({ pinnedId: "b" }), t).text).toBe(
      'spectrum.inspector_focus_selected:{"sensor":"Rear","freq":"30.0","value":"8.0","bands":"bands.engine_1x"}',
    );
    expect(inspectorText(input({ entries: [] }), t)).toEqual({
      mode: "idle",
      text: "spectrum.inspector_idle",
    });
  });

  test("hover lines are throttled and never announced; focus lines are announced once", () => {
    let now = 0;
    const timers: Array<{ at: number; run: () => void }> = [];
    const shown: string[] = [];
    const announced: string[] = [];
    const feed = createInspectorFeed({
      show: (text) => shown.push(text),
      announce: (text) => announced.push(text),
      now: () => now,
      schedule: (run, delayMs) => {
        const timer = { at: now + delayMs, run };
        timers.push(timer);
        return () => timers.splice(timers.indexOf(timer), 1);
      },
    });
    const advance = (ms: number) => {
      now += ms;
      for (const timer of timers.filter((entry) => entry.at <= now)) {
        timers.splice(timers.indexOf(timer), 1);
        timer.run();
      }
    };

    feed.update({ mode: "hover", text: "h1" });
    feed.update({ mode: "hover", text: "h2" });
    feed.update({ mode: "hover", text: "h3" });
    expect(shown).toEqual(["h1"]);
    advance(33);
    expect(shown).toEqual(["h1", "h3"]);
    expect(announced).toEqual([]);

    feed.update({ mode: "hover", text: "h4" });
    feed.update({ mode: "focus", text: "peak" });
    advance(100);
    expect(shown).toEqual(["h1", "h3", "peak"]);
    expect(announced).toEqual(["peak"]);
    feed.update({ mode: "focus", text: "peak" });
    expect(announced).toEqual(["peak"]);
  });
});

describe("overlay", () => {
  const base: OverlayInput = {
    chartLoadError: null,
    prepareError: null,
    payloadError: null,
    hasReceivedPayload: true,
    wsState: "connected",
    chartLoading: false,
    hasData: true,
  };
  const message = (overrides: Partial<OverlayInput>) =>
    overlayMessage({ ...base, ...overrides }, t);

  test("hides while live data is drawn", () => {
    expect(message({})).toBeNull();
  });

  test("explains the most important problem first", () => {
    expect(message({ chartLoadError: "x", payloadError: "bad" })).toBe(
      'spectrum.chart_load_error:{"message":"x"}',
    );
    expect(message({ prepareError: "y", payloadError: "bad" })).toBe(
      'spectrum.frame_prepare_error:{"message":"y"}',
    );
    expect(message({ payloadError: "bad", wsState: "stale" })).toBe("bad");
    expect(message({ wsState: "connecting", hasReceivedPayload: false })).toBe(
      "spectrum.loading",
    );
    expect(message({ wsState: "reconnecting" })).toBe("ws.connecting");
    expect(message({ wsState: "stale" })).toBe("spectrum.stale");
    expect(message({ chartLoading: true })).toBe("spectrum.loading");
    expect(message({ hasData: false })).toBe("spectrum.empty");
  });
});

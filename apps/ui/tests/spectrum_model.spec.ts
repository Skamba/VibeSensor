import { describe, expect, test } from "vitest";

import {
  activeFrequency,
  bandStatus,
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
// A sensor's strength (dB above its floor) is not its peak bin's chart level;
// it ranks by mg, as the report ranks locations, not by dB.
const levels: SensorLevels = {
  strengthDb: (id) => ({ a: 6, b: 9 })[id] ?? null,
  peakMg: (id) => ({ a: 120, b: 80 })[id] ?? null,
  topPeakHz: (id) => ({ a: 19, b: 31 })[id] ?? null,
};
const bands = orderBands(
  {
    basis_speed_source: null,
    wheel: { rpm: 600, mode: null, reason: null },
    driveshaft: { rpm: null, mode: null, reason: null },
    engine: { rpm: null, mode: null, reason: null },
    order_bands: [
      { key: "wheel_1x", code: "T1", center_hz: 20, tolerance: 0.1 },
      { key: "engine_1x", code: "E1", center_hz: 30, tolerance: 0.1 },
      { key: "broken", code: "X", center_hz: 0, tolerance: 0.1 },
    ],
  },
  null,
  t,
);

// Every band leads with the report's workshop label (T1, P1, E2).
const coded = (code: string, band: string) =>
  t("bands.with_code", { code, band });
const wheelLabel = coded("T1", "bands.wheel_1x");
const engineLabel = coded(
  "E1",
  t("bands.with_basis", {
    band: "bands.engine_1x",
    basis: "bands.basis.estimated_top_gear",
  }),
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
        [wheelLabel, 18, 22],
        [engineLabel, 27, 33],
      ],
    );
    expect(orderBands(null, null, t)).toEqual([]);
  });

  test("engine bands say whether the RPM is measured or assumes top gear", () => {
    const measured = orderBands(
      {
        basis_speed_source: null,
        wheel: { rpm: 600, mode: null, reason: null },
        driveshaft: { rpm: 1800, mode: null, reason: null },
        engine: { rpm: 2400, mode: "measured", reason: null },
        order_bands: [
          {
            key: "driveshaft_engine_1x",
            code: "P1/E1",
            center_hz: 40,
            tolerance: 0.1,
          },
          { key: "driveshaft_1x", code: "P1", center_hz: 30, tolerance: 0.1 },
        ],
      },
      "PHEV",
      t,
    );
    expect(measured.map((band) => band.label)).toEqual([
      coded(
        "P1/E1",
        t("bands.with_basis", {
          band: "bands.driveshaft_engine_1x",
          basis: "bands.basis.measured",
        }),
      ),
      coded("P1", "bands.driveshaft_1x"),
    ]);
  });

  test("an EV's driveline band is its motor and it has no engine bands", () => {
    const ev = orderBands(
      {
        basis_speed_source: null,
        wheel: { rpm: 600, mode: null, reason: null },
        driveshaft: { rpm: 5400, mode: null, reason: null },
        engine: { rpm: 5400, mode: "calculated", reason: null },
        order_bands: [
          { key: "wheel_1x", code: "T1", center_hz: 10, tolerance: 0.1 },
          {
            key: "driveshaft_engine_1x",
            code: "P1/E1",
            center_hz: 90,
            tolerance: 0.1,
          },
          { key: "engine_2x", code: "E2", center_hz: 180, tolerance: 0.1 },
        ],
      },
      "EV",
      t,
    );
    expect(ev.map((band) => band.label)).toEqual([
      coded("T1", "bands.wheel_1x"),
      coded("P1/E1", "bands.motor_1x"),
    ]);
  });

  test("an engine's own orders are engine bands and its firing order says so", () => {
    const six = orderBands(
      {
        basis_speed_source: null,
        wheel: { rpm: 600, mode: null, reason: null },
        driveshaft: { rpm: 1800, mode: null, reason: null },
        engine: { rpm: 2400, mode: "measured", reason: null },
        order_bands: [
          { key: "engine_1x", code: "E1", center_hz: 40, tolerance: 0.1 },
          {
            key: "engine_3x",
            code: "E3",
            center_hz: 120,
            tolerance: 0.1,
            firing: true,
          },
          { key: "engine_1_5x", code: "E1.5", center_hz: 60, tolerance: 0.1 },
        ],
      },
      "ICE",
      t,
    );
    const basis = "bands.basis.measured";
    expect(six.map((band) => band.label)).toEqual([
      coded("E1", t("bands.with_basis", { band: "bands.engine_1x", basis })),
      coded(
        "E3",
        t("bands.with_basis", {
          band: t("bands.firing", {
            band: t("bands.engine_order", { order: "3x" }),
          }),
          basis,
        }),
      ),
      coded(
        "E1.5",
        t("bands.with_basis", {
          band: t("bands.engine_order", { order: "1.5x" }),
          basis,
        }),
      ),
    ]);
  });

  test("the band legend lists the bands at the inspected frequency", () => {
    expect(activeFrequency(input())).toBe(20);
    expect(bandsAt(bands, 20).map((band) => band.label)).toEqual([wheelLabel]);
    expect(activeFrequency(input({ cursorIdx: 2 }))).toBe(30);
    expect(activeFrequency(input({ pinnedId: "b" }))).toBe(30);
    expect(bandsAt(bands, 40)).toEqual([]);
  });
});

describe("band status", () => {
  const blank = { rpm: null, mode: null, reason: null };
  const speeds = (
    overrides: Partial<NonNullable<Parameters<typeof orderBands>[0]>>,
  ) => ({
    basis_speed_source: null,
    wheel: blank,
    driveshaft: blank,
    engine: blank,
    order_bands: [],
    ...overrides,
  });
  const states = (status: ReturnType<typeof bandStatus>) =>
    status.families.map((family) => [family.key, family.state, family.note]);

  test("without a car the spectrum says bands need one", () => {
    expect(
      bandStatus(
        {
          carActive: false,
          fuelType: null,
          speeds: null,
          speedMps: 20,
          gpsReceiverMissing: false,
        },
        t,
      ),
    ).toEqual({ message: "spectrum.bands.need_car", families: [] });
  });

  test("names the reference each blank family needs and the engine basis", () => {
    const status = bandStatus(
      {
        carActive: true,
        fuelType: null,
        speeds: speeds({
          wheel: { rpm: 600, mode: null, reason: null },
          driveshaft: { rpm: null, mode: null, reason: "missing_final_drive" },
          engine: { rpm: 2000, mode: "estimated", reason: null },
        }),
        speedMps: 20,
        gpsReceiverMissing: false,
      },
      t,
    );
    expect(status.message).toBeNull();
    expect(states(status)).toEqual([
      ["wheel", "on", null],
      [
        "driveline",
        "missing",
        "spectrum.bands.needs.driveline.missing_final_drive",
      ],
      ["engine", "on", "bands.basis.estimated_top_gear"],
    ]);
  });

  test("an EV lists its motor and no engine family", () => {
    const status = bandStatus(
      {
        carActive: true,
        fuelType: "EV",
        speeds: speeds({
          wheel: { rpm: 600, mode: null, reason: null },
          driveshaft: { rpm: 5400, mode: null, reason: null },
          engine: { rpm: null, mode: null, reason: "missing_gear_ratio" },
        }),
        speedMps: 20,
        gpsReceiverMissing: false,
      },
      t,
    );
    expect(status.families.map((family) => [family.key, family.label])).toEqual(
      [
        ["wheel", "spectrum.bands.family.wheel"],
        ["driveline", "spectrum.bands.family.motor"],
      ],
    );
  });

  test("without speed it says why: parked, no speed, or no GPS receiver", () => {
    const waiting = speeds({
      wheel: { rpm: null, mode: null, reason: "speed_unavailable" },
    });
    const message = (speedMps: number | null, gpsReceiverMissing: boolean) =>
      bandStatus(
        {
          carActive: true,
          fuelType: null,
          speeds: waiting,
          speedMps,
          gpsReceiverMissing,
        },
        t,
      ).message;
    expect(message(0, false)).toBe("spectrum.bands.need_motion");
    expect(message(null, false)).toBe("spectrum.bands.need_speed");
    expect(message(null, true)).toBe(
      "spectrum.bands.need_speed speed.gps_no_receiver.title: speed.gps_no_receiver.body",
    );
    expect(
      states(
        bandStatus(
          {
            carActive: true,
            fuelType: null,
            speeds: null,
            speedMps: null,
            gpsReceiverMissing: false,
          },
          t,
        ),
      ).map(([, state]) => state),
    ).toEqual(["waiting", "waiting", "waiting"]);
  });
});

describe("trace focus", () => {
  test("focuses the pinned trace, else the strongest in mg (not the most dB above its floor)", () => {
    expect(focusEntry(entries, null, levels)?.id).toBe("a");
    expect(focusEntry(entries, "b", levels)?.id).toBe("b");
    expect(focusEntry(entries, "gone", levels)?.id).toBe("a");
  });

  test("legend chips show each level and which trace is isolated", () => {
    const all = legendModel(entries, null, levels, t);
    expect(all?.allActive).toBe(true);
    expect(all?.items.map((item) => [item.detail, item.state])).toEqual([
      ['spectrum.legend.sensor_level:{"value":"6"}', undefined],
      ['spectrum.legend.sensor_level:{"value":"9"}', undefined],
    ]);
    const pinned = legendModel(entries, "a", levels, t);
    expect(pinned?.allActive).toBe(false);
    expect(pinned?.items.map((item) => item.state)).toEqual([
      "active",
      "muted",
    ]);
    expect(pinned?.items[0]?.title).toBe("spectrum.legend.clear_focus");
    expect(pinned?.items[1]?.ariaLabel).toBe(
      'Rear. spectrum.legend.state_inactive. spectrum.legend.sensor_level:{"value":"9"}',
    );
    const noLevels = legendModel(
      entries,
      null,
      { strengthDb: () => null, peakMg: () => null, topPeakHz: () => null },
      t,
    );
    expect(noLevels?.items[0]?.detail).toBe("spectrum.legend.state_visible");
    expect(legendModel([], null, levels, t)).toBeNull();
  });
});

describe("inspector", () => {
  test("describes the hovered bin in mg, else the focused sensor's strength above floor, else a hint", () => {
    expect(inspectorText(input({ cursorIdx: 2 }), t)).toEqual({
      mode: "hover",
      text: `spectrum.inspector_hover:${JSON.stringify({ sensor: "Front", freq: "30.0", value: "0.14" })} · ${engineLabel}`,
    });
    // A frequency outside every order band gets no band suffix at all.
    expect(inspectorText(input({ cursorIdx: 3 }), t).text).toBe(
      `spectrum.inspector_hover:${JSON.stringify({ sensor: "Front", freq: "40.0", value: "0.11" })}`,
    );
    expect(inspectorText(input(), t)).toEqual({
      mode: "focus",
      text: `spectrum.inspector_focus_strongest:{"sensor":"Front","freq":"20.0","mg":"120","value":"6"} · ${wheelLabel}`,
    });
    expect(inspectorText(input({ pinnedId: "b" }), t).text).toBe(
      `spectrum.inspector_focus_selected:${JSON.stringify({ sensor: "Rear", freq: "30.0", mg: "80", value: "9" })} · ${engineLabel}`,
    );
    expect(inspectorText(input({ entries: [] }), t)).toEqual({
      mode: "idle",
      text: "spectrum.inspector_idle",
    });
  });

  test("hover lines are throttled; focus lines show at once, each change only once", () => {
    let now = 0;
    const timers: Array<{ at: number; run: () => void }> = [];
    const shown: string[] = [];
    const feed = createInspectorFeed({
      show: (text) => shown.push(text),
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

    feed.update({ mode: "hover", text: "h4" });
    feed.update({ mode: "focus", text: "peak" });
    advance(100);
    expect(shown).toEqual(["h1", "h3", "peak"]);
    feed.update({ mode: "focus", text: "peak" });
    expect(shown).toEqual(["h1", "h3", "peak"]);
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

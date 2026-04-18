import { expect, test } from "@playwright/test";

import { SpectrumInteractionController } from "../src/app/runtime/spectrum_interaction_controller";
import type {
  SpectrumInspectorRenderModel,
  SpectrumPanelView,
} from "../src/app/runtime/spectrum_panel_view";
import { createElementStub } from "./spectrum_test_support";

function createPanelStub(): {
  panel: SpectrumPanelView;
  onBandToggle: (() => void) | null;
  inspectorCalls: SpectrumInspectorRenderModel[];
  inspectorText: string;
} {
  let onBandToggle: (() => void) | null = null;
  let inspectorText = "";
  const inspectorCalls: SpectrumInspectorRenderModel[] = [];

  return {
    panel: {
        chartDom: {
          specChartWrap: createElementStub("div"),
          specChart: createElementStub("div"),
        },
        bindBandToggle(handler) {
          onBandToggle = handler;
        },
        bindBandToggleModel() {},
        bindSensorLegendModel() {},
        bindBandLegendModel() {},
        renderHeader() {},
        renderOverlay() {},
        renderInspector(model) {
          inspectorText = model.text;
          inspectorCalls.push(model);
        },
      },
      get onBandToggle() {
        return onBandToggle;
      },
      get inspectorCalls() {
        return inspectorCalls;
      },
      get inspectorText() {
        return inspectorText;
      },
  };
}

function createTimerHarness(): {
  advanceBy(ms: number): void;
  cancelTimeout(handle: number): void;
  nowMs(): number;
  scheduleTimeout(callback: () => void, delayMs: number): number;
} {
  let nowMs = 0;
  let nextHandle = 1;
  const timeouts = new Map<number, { atMs: number; callback: () => void }>();

  function flushDueTimeouts(): void {
    while (true) {
      const due = [...timeouts.entries()]
        .filter(([, entry]) => entry.atMs <= nowMs)
        .sort((left, right) => left[1].atMs - right[1].atMs)[0];
      if (!due) {
        return;
      }
      const [handle, entry] = due;
      timeouts.delete(handle);
      entry.callback();
    }
  }

  return {
    advanceBy(ms: number): void {
      nowMs += ms;
      flushDueTimeouts();
    },
    cancelTimeout(handle: number): void {
      timeouts.delete(handle);
    },
    nowMs(): number {
      return nowMs;
    },
    scheduleTimeout(callback: () => void, delayMs: number): number {
      const handle = nextHandle;
      nextHandle += 1;
      timeouts.set(handle, {
        atMs: nowMs + delayMs,
        callback,
      });
      return handle;
    },
  };
}

test.describe("SpectrumInteractionController", () => {
  test("renders legend models and toggles isolated series", () => {
    const panel = createPanelStub();

    const strengthDbById = new Map([
      ["sensor-a", 12],
      ["sensor-b", 8],
    ]);
    let isolatedSeries: number | null = null;

    const controller = new SpectrumInteractionController({
      panel: panel.panel,
      t: (key, vars) => {
        if (key === "spectrum.legend.state_all_visible") return "All visible";
        if (key === "spectrum.legend.state_visible") return "Visible";
        if (key === "spectrum.legend.state_isolated") return "Isolated";
        if (key === "spectrum.legend.state_inactive") return "Inactive";
        if (key === "spectrum.legend.sensor_level") {
          return `${String(vars?.value)} dB`;
        }
        if (key === "spectrum.legend.all_series") return "All sensor traces";
        if (key === "spectrum.legend.clear_focus") return "Clear focus";
        if (key === "spectrum.legend.focus_series") return `Focus ${String(vars?.sensor)}`;
        if (key === "spectrum.inspector_idle") return "Idle";
        if (key === "spectrum.inspector_no_band") return "No reference band";
        if (key === "spectrum.bands.show") return "Show reference bands";
        if (key === "spectrum.bands.hide") return "Hide reference bands";
        if (key === "spectrum.bands.none") return "No reference band";
        return vars?.sensor ? `${key}:${String(vars.sensor)}` : key;
      },
      getStrengthDb: (entryId) => strengthDbById.get(entryId) ?? null,
      getTopPeakHz: (entryId) => (entryId === "sensor-a" ? 10 : 20),
      setSeriesIsolation: (seriesIndex) => {
        isolatedSeries = seriesIndex;
      },
      requestPlotRefresh: () => undefined,
    });

    const entries = [
      { id: "sensor-a", label: "Front Right Wheel", color: "#ff5500", values: [12, 11] },
      { id: "sensor-b", label: "Rear Left Wheel", color: "#3366ff", values: [8, 7] },
    ];

    controller.sync({
      entries,
      freqAxis: [10, 20],
      chartBands: [],
    });

    expect(controller.bandToggleModel.value).toEqual({
      disabled: true,
      hasBands: false,
      bandsVisible: false,
      hidden: true,
      pressed: "false",
      text: "Show reference bands",
    });
    expect(controller.sensorLegendModel.value?.items[0]?.detailText).toBe("12.0 dB");
    expect(controller.sensorLegendModel.value?.items[0]?.ariaPressed).toBe(false);
    expect(controller.sensorLegendModel.value?.items[1]?.detailText).toBe("8.0 dB");
    expect(isolatedSeries).toBeNull();

    controller.sensorLegendHandlersModel.value?.onSelect("sensor-a");
    expect(controller.sensorLegendModel.value?.items[0]?.detailText).toBe("12.0 dB");
    expect(controller.sensorLegendModel.value?.items[0]?.ariaPressed).toBe(true);
    expect(controller.sensorLegendModel.value?.items[0]?.active).toBe(true);
    expect(controller.sensorLegendModel.value?.items[1]?.detailText).toBe("8.0 dB");
    expect(controller.sensorLegendModel.value?.items[1]?.muted).toBe(true);
    expect(isolatedSeries).toBe(1);

    strengthDbById.set("sensor-a", 13);
    controller.sync({
      entries: [
        { ...entries[0], values: [13, 12] },
        entries[1],
      ],
      freqAxis: [10, 20],
      chartBands: [],
    });

    expect(controller.sensorLegendModel.value?.items[0]?.detailText).toBe("13.0 dB");
    expect(controller.sensorLegendModel.value?.items[0]?.ariaPressed).toBe(true);

    controller.sensorLegendHandlersModel.value?.onSelect("sensor-a");
    expect(controller.sensorLegendModel.value?.items[0]?.detailText).toBe("13.0 dB");
    expect(controller.sensorLegendModel.value?.items[0]?.ariaPressed).toBe(false);
    expect(controller.sensorLegendModel.value?.items[0]?.active).toBe(false);
    expect(controller.sensorLegendModel.value?.items[1]?.detailText).toBe("8.0 dB");
    expect(controller.sensorLegendModel.value?.items[1]?.muted).toBe(false);
    expect(isolatedSeries).toBeNull();

    expect(panel.onBandToggle).not.toBeNull();
  });

  test("throttles hover inspector updates and keeps hover silent for aria-live", () => {
    const panel = createPanelStub();
    const timers = createTimerHarness();

    const controller = new SpectrumInteractionController({
      panel: panel.panel,
      t: (key, vars) => {
        if (key === "spectrum.legend.state_all_visible") return "All visible";
        if (key === "spectrum.legend.state_visible") return "Visible";
        if (key === "spectrum.legend.state_isolated") return "Isolated";
        if (key === "spectrum.legend.state_inactive") return "Inactive";
        if (key === "spectrum.legend.sensor_level") return `${String(vars?.value)} dB`;
        if (key === "spectrum.legend.all_series") return "All sensor traces";
        if (key === "spectrum.legend.clear_focus") return "Clear focus";
        if (key === "spectrum.legend.focus_series") return `Focus ${String(vars?.sensor)}`;
        if (key === "spectrum.inspector_idle") return "Idle";
        if (key === "spectrum.inspector_no_band") return "No reference band";
        if (key === "spectrum.inspector_hover") {
          return `Hover:${String(vars?.sensor)}:${String(vars?.freq)}:${String(vars?.value)}:${String(vars?.bands)}`;
        }
        if (key === "spectrum.inspector_focus_selected") {
          return `Selected:${String(vars?.sensor)}:${String(vars?.freq)}:${String(vars?.value)}:${String(vars?.bands)}`;
        }
        if (key === "spectrum.inspector_focus_strongest") {
          return `Strongest:${String(vars?.sensor)}:${String(vars?.freq)}:${String(vars?.value)}:${String(vars?.bands)}`;
        }
        return key;
      },
      getStrengthDb: (entryId) => (entryId === "sensor-a" ? 12 : 8),
      getTopPeakHz: (entryId) => (entryId === "sensor-a" ? 10 : 20),
      setSeriesIsolation: () => undefined,
      requestPlotRefresh: () => undefined,
      scheduleTimeout: timers.scheduleTimeout,
      cancelTimeout: timers.cancelTimeout,
      nowMs: timers.nowMs,
    });

    controller.sync({
      entries: [
        { id: "sensor-a", label: "Front Right Wheel", color: "#ff5500", values: [12, 11, 10] },
        { id: "sensor-b", label: "Rear Left Wheel", color: "#3366ff", values: [8, 7, 6] },
      ],
      freqAxis: [10, 20, 30],
      chartBands: [],
    });

    panel.inspectorCalls.length = 0;

    controller.setCursorDataIndex(0);
    controller.setCursorDataIndex(1);
    controller.setCursorDataIndex(2);

    expect(panel.inspectorCalls).toHaveLength(1);
    expect(panel.inspectorCalls[0]).toEqual({
      text: "Hover:Front Right Wheel:10.0:12.0:No reference band",
      announce: false,
    });

    timers.advanceBy(33);

    expect(panel.inspectorCalls).toHaveLength(2);
    expect(panel.inspectorCalls[1]).toEqual({
      text: "Hover:Front Right Wheel:30.0:10.0:No reference band",
      announce: false,
    });

    panel.inspectorCalls.length = 0;
    controller.setCursorDataIndex(null);
    controller.sensorLegendHandlersModel.value?.onSelect("sensor-a");

    expect(panel.inspectorCalls.at(-1)).toEqual({
      text: "Selected:Front Right Wheel:10.0:12.0:No reference band",
      announce: true,
    });
  });
});

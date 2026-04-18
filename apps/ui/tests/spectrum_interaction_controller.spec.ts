import { expect, test } from "@playwright/test";

import { SpectrumInteractionController } from "../src/app/runtime/spectrum_interaction_controller";
import type {
  SpectrumPanelView,
} from "../src/app/runtime/spectrum_panel_view";
import { createElementStub } from "./spectrum_test_support";

function createPanelStub(): {
  panel: SpectrumPanelView;
  onBandToggle: (() => void) | null;
  inspectorText: string;
} {
  let onBandToggle: (() => void) | null = null;
  let inspectorText = "";

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
        renderInspectorText(text) {
          inspectorText = text;
        },
      },
      get onBandToggle() {
        return onBandToggle;
      },
      get inspectorText() {
        return inspectorText;
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
      hasBands: false,
      bandsVisible: false,
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
});

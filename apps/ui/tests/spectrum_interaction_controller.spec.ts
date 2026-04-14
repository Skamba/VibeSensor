import { expect, test } from "@playwright/test";

import { SpectrumInteractionController } from "../src/app/runtime/spectrum_interaction_controller";
import type {
  SpectrumBandLegendModel,
  SpectrumPanelView,
  SpectrumSensorLegendModel,
} from "../src/app/runtime/spectrum_panel_view";

function createPanelStub(): {
  panel: SpectrumPanelView;
  bandToggleModel: { hasBands: boolean; bandsVisible: boolean; text: string } | null;
  sensorLegend: {
    model: SpectrumSensorLegendModel | null;
    handlers: {
      onReset: () => void;
      onSelect: (entryId: string) => void;
    } | null;
  };
  bandLegendModel: SpectrumBandLegendModel | null;
  inspectorText: string;
} {
  let bandToggleModel: { hasBands: boolean; bandsVisible: boolean; text: string } | null = null;
  let sensorLegend: {
    model: SpectrumSensorLegendModel | null;
    handlers: {
      onReset: () => void;
      onSelect: (entryId: string) => void;
    } | null;
  } = {
    model: null,
    handlers: null,
  };
  let bandLegendModel: SpectrumBandLegendModel | null = null;
  let inspectorText = "";

  return {
    panel: {
      bindBandToggle() {},
      renderHeader() {},
      renderOverlay() {},
      renderBandToggle(model) {
        bandToggleModel = model;
      },
      renderSensorLegend(model, handlers) {
        sensorLegend = {
          model,
          handlers: handlers ?? null,
        };
      },
      renderBandLegend(model) {
        bandLegendModel = model;
      },
      renderInspectorText(text) {
        inspectorText = text;
      },
    },
    get bandToggleModel() {
      return bandToggleModel;
    },
    get sensorLegend() {
      return sensorLegend;
    },
    get bandLegendModel() {
      return bandLegendModel;
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

    expect(panel.bandToggleModel).toEqual({
      hasBands: false,
      bandsVisible: false,
      text: "Show reference bands",
    });
    expect(panel.sensorLegend.model?.items[0]?.detailText).toBe("12.0 dB");
    expect(panel.sensorLegend.model?.items[0]?.ariaPressed).toBe(false);
    expect(panel.sensorLegend.model?.items[1]?.detailText).toBe("8.0 dB");
    expect(isolatedSeries).toBeNull();

    panel.sensorLegend.handlers?.onSelect("sensor-a");
    expect(panel.sensorLegend.model?.items[0]?.detailText).toBe("12.0 dB");
    expect(panel.sensorLegend.model?.items[0]?.ariaPressed).toBe(true);
    expect(panel.sensorLegend.model?.items[0]?.active).toBe(true);
    expect(panel.sensorLegend.model?.items[1]?.detailText).toBe("8.0 dB");
    expect(panel.sensorLegend.model?.items[1]?.muted).toBe(true);
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

    expect(panel.sensorLegend.model?.items[0]?.detailText).toBe("13.0 dB");
    expect(panel.sensorLegend.model?.items[0]?.ariaPressed).toBe(true);

    panel.sensorLegend.handlers?.onSelect("sensor-a");
    expect(panel.sensorLegend.model?.items[0]?.detailText).toBe("13.0 dB");
    expect(panel.sensorLegend.model?.items[0]?.ariaPressed).toBe(false);
    expect(panel.sensorLegend.model?.items[0]?.active).toBe(false);
    expect(panel.sensorLegend.model?.items[1]?.detailText).toBe("8.0 dB");
    expect(panel.sensorLegend.model?.items[1]?.muted).toBe(false);
    expect(isolatedSeries).toBeNull();
  });
});

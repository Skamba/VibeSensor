import { expect, test } from "@playwright/test";

import { SpectrumInteractionController } from "../src/app/runtime/spectrum_interaction_controller";
import { createSpectrumPanelView } from "../src/app/runtime/spectrum_panel_view";
import { installWindowGlobal } from "./async_test_helpers";
import { createElementStub, installDocumentStub } from "./spectrum_test_support";

test.describe("SpectrumInteractionController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("reuses legend buttons across live refreshes and click toggles", () => {
    const restoreDocument = installDocumentStub();
    try {
      const legend = createElementStub("div");
      const inspector = createElementStub("div");
      const bandToggle = createElementStub("button");
      const panel = createSpectrumPanelView({
        dom: {
          legend,
          bandLegend: createElementStub("div"),
          spectrumBandToggle: bandToggle,
          spectrumInspector: inspector,
        },
      });

      const strengthDbById = new Map([
        ["sensor-a", 12],
        ["sensor-b", 8],
      ]);
      let isolatedSeries: number | null = null;

      const controller = new SpectrumInteractionController({
        panel,
        t: (key, vars) => {
          if (key === "spectrum.legend.state_all_visible") return "All visible";
          if (key === "spectrum.legend.state_visible") return "Visible";
          if (key === "spectrum.legend.state_isolated") return "Isolated";
          if (key === "spectrum.legend.state_inactive") return "Inactive";
          if (key === "spectrum.legend.sensor_level") {
            return `Sensor level: ${String(vars?.value)} dB`;
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

      const allButton = legend.children[0];
      const sensorButton = legend.children[1];
      const sensorMeta = sensorButton.children[1].children[1];
      expect(sensorMeta.textContent).toBe("Visible · Sensor level: 12.0 dB");
      expect(isolatedSeries).toBeNull();

      sensorButton.click();
      expect(legend.children[0]).toBe(allButton);
      expect(legend.children[1]).toBe(sensorButton);
      expect(sensorButton.getAttribute("aria-pressed")).toBe("true");
      expect(sensorMeta.textContent).toBe("Isolated · Sensor level: 12.0 dB");
      expect(isolatedSeries).toBe(1);

      strengthDbById.set("sensor-a", 13);
      const refreshedEntries = [
        { ...entries[0], values: [13, 12] },
        entries[1],
      ];
      controller.sync({
        entries: refreshedEntries,
        freqAxis: [10, 20],
        chartBands: [],
      });

      expect(legend.children[0]).toBe(allButton);
      expect(legend.children[1]).toBe(sensorButton);
      expect(sensorMeta.textContent).toBe("Isolated · Sensor level: 13.0 dB");
      expect(sensorButton.getAttribute("aria-pressed")).toBe("true");

      sensorButton.click();
      expect(legend.children[0]).toBe(allButton);
      expect(legend.children[1]).toBe(sensorButton);
      expect(sensorButton.getAttribute("aria-pressed")).toBe("false");
      expect(sensorMeta.textContent).toBe("Visible · Sensor level: 13.0 dB");
      expect(isolatedSeries).toBeNull();
    } finally {
      restoreDocument();
    }
  });
});

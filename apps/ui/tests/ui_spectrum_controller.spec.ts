import { expect, test } from "@playwright/test";

import type { SpectrumPanelView } from "../src/app/runtime/spectrum_panel_view";
import { createAppState } from "../src/app/ui_app_state";
import { installWindowGlobal } from "./async_test_helpers";
import { createElementStub, installDocumentStub } from "./spectrum_test_support";

async function importUiSpectrumController() {
  return (await import("../src/app/runtime/ui_spectrum_controller")).UiSpectrumController;
}

function createPanelStub(): {
  panel: SpectrumPanelView;
  lastHeaderModel: { hintText: string; titleText: string } | null;
  lastOverlayMessage: string | null;
} {
  let lastHeaderModel: { hintText: string; titleText: string } | null = null;
  let lastOverlayMessage: string | null = null;

  return {
    panel: {
      chartDom: {
        specChartWrap: createElementStub("div"),
        specChart: createElementStub("div"),
      },
      bindBandToggle() {},
      renderHeader(model) {
        lastHeaderModel = model;
      },
      renderOverlay(message: string | null) {
        lastOverlayMessage = message;
      },
      renderBandToggle() {},
      renderSensorLegend() {},
      renderBandLegend() {},
      renderInspectorText() {},
    },
    get lastHeaderModel() {
      return lastHeaderModel;
    },
    get lastOverlayMessage() {
      return lastOverlayMessage;
    },
  };
}

test.describe("UiSpectrumController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("renders the connecting overlay through the coordinator surface", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState = "connecting";
      state.transport.hasReceivedPayload = false;
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });

      expect(panel.lastOverlayMessage).toBe("spectrum.loading");
    } finally {
      restoreDocument();
    }
  });

  test("reacts to transport state changes without explicit overlay callbacks", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState = "connecting";
      state.transport.hasReceivedPayload = false;
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });

      state.transport.wsState = "stale";

      expect(panel.lastOverlayMessage).toBe("spectrum.stale");
    } finally {
      restoreDocument();
    }
  });

  test("shows the loading overlay while the chart chunk is still loading", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState = "connected";
      state.transport.hasReceivedPayload = true;
      state.spectrum.hasSpectrumData = true;
      state.spectrum.chartLoading = true;
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => key,
      });

      expect(panel.lastOverlayMessage).toBe("spectrum.loading");
    } finally {
      restoreDocument();
    }
  });

  test("shows chart load errors through the overlay", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState = "connected";
      state.transport.hasReceivedPayload = true;
      state.spectrum.hasSpectrumData = true;
      state.spectrum.chartLoadErrorDetail = "chunk timeout";
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key, vars) => {
          if (key === "spectrum.chart_load_error") {
            return `chart load failed: ${String(vars?.message)}`;
          }
          return key;
        },
      });

      expect(panel.lastOverlayMessage).toBe("chart load failed: chunk timeout");
    } finally {
      restoreDocument();
    }
  });

  test("updates spectrum header and overlay when the language changes", async () => {
    const restoreDocument = installDocumentStub();
    try {
      const UiSpectrumController = await importUiSpectrumController();
      const state = createAppState();
      state.transport.wsState = "stale";
      const panel = createPanelStub();

      new UiSpectrumController({
        state,
        panel: panel.panel,
        t: (key) => `${state.shell.lang}:${key}`,
      });

      expect(panel.lastHeaderModel).toEqual({
        titleText: "en:chart.spectrum_title",
        hintText: "en:spectrum.controls_hint",
      });
      expect(panel.lastOverlayMessage).toBe("en:spectrum.stale");

      state.shell.lang = "nl";

      expect(panel.lastHeaderModel).toEqual({
        titleText: "nl:chart.spectrum_title",
        hintText: "nl:spectrum.controls_hint",
      });
      expect(panel.lastOverlayMessage).toBe("nl:spectrum.stale");
    } finally {
      restoreDocument();
    }
  });
});

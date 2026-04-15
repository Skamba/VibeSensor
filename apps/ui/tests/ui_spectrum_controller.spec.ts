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
  lastOverlayMessage: string | null;
} {
  let lastOverlayMessage: string | null = null;

  return {
    panel: {
      chartDom: {
        specChartWrap: createElementStub("div"),
        specChart: createElementStub("div"),
      },
      bindBandToggle() {},
      renderHeader() {},
      renderOverlay(message: string | null) {
        lastOverlayMessage = message;
      },
      renderBandToggle() {},
      renderSensorLegend() {},
      renderBandLegend() {},
      renderInspectorText() {},
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
});

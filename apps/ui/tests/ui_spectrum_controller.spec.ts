import { expect, test } from "@playwright/test";

import type { UiSpectrumDom } from "../src/app/dom/spectrum_dom";
import { createAppState } from "../src/app/ui_app_state";
import { installWindowGlobal } from "./async_test_helpers";
import { createElementStub, installDocumentStub } from "./spectrum_test_support";

async function importUiSpectrumController() {
  return (await import("../src/app/runtime/ui_spectrum_controller")).UiSpectrumController;
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
      const overlay = createElementStub("div");

      const controller = new UiSpectrumController({
        state,
        dom: {
          specChartWrap: createElementStub("div"),
          specChart: createElementStub("div"),
          spectrumOverlay: overlay,
          spectrumInspector: null,
          legend: null,
          bandLegend: null,
          spectrumBandToggle: null,
        } as unknown as UiSpectrumDom,
        t: (key) => key,
      });

      controller.updateSpectrumOverlay();

      expect(overlay.hidden).toBe(false);
      expect(overlay.textContent).toBe("spectrum.loading");
    } finally {
      restoreDocument();
    }
  });
});

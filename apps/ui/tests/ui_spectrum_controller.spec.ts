import type uPlot from "uplot";
import { expect, test } from "@playwright/test";

import { UiSpectrumController } from "../src/app/runtime/ui_spectrum_controller";
import { createAppState } from "../src/app/ui_app_state";
import type { UiDomElements } from "../src/app/ui_dom_registry";
import { installWindowGlobal } from "./async_test_helpers";

test.describe("UiSpectrumController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("reuses the same band plugin across repeated plugin reads", () => {
    const originalDocument = globalThis.document;
    const originalGetComputedStyle = globalThis.getComputedStyle;

    (globalThis as { document?: Document }).document = {
      documentElement: {} as HTMLElement,
    } as Document;
    globalThis.getComputedStyle = (() =>
      ({
        getPropertyValue: () => "",
      }) as CSSStyleDeclaration) as typeof getComputedStyle;

    try {
      const controller = new UiSpectrumController({
        state: createAppState(),
        els: {
          spectrumBandToggle: null,
        } as unknown as UiDomElements,
        t: (key) => key,
      });

      const internals = controller as unknown as {
        spectrumPlugins(): uPlot.Plugin[];
      };

      const [firstPlugin] = internals.spectrumPlugins();
      const [secondPlugin] = internals.spectrumPlugins();

      expect(firstPlugin).toBe(secondPlugin);
    } finally {
      (globalThis as { document?: Document }).document = originalDocument;
      globalThis.getComputedStyle = originalGetComputedStyle;
    }
  });
});

import { expect, test } from "@playwright/test";

import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import type { EspFlashPanelActionHandlers } from "../src/app/views/esp_flash_panel";

test("bindHandlers uses panel action surfaces instead of raw DOM bindings", () => {
  let handlers: EspFlashPanelActionHandlers | null = null;
  const feature = createEspFlashFeature({
    panel: {
      bindActions(nextHandlers) {
        handlers = nextHandlers;
      },
      render() {},
    },
    t: (key) => key,
    escapeHtml: (value) => String(value ?? ""),
    showError() {},
  });

  expect(() => feature.bindHandlers()).not.toThrow();
  expect(handlers).not.toBeNull();
  expect(typeof handlers?.onStart).toBe("function");
  expect(typeof handlers?.onCancel).toBe("function");
  expect(typeof handlers?.onRefreshPorts).toBe("function");
  expect(typeof handlers?.onSelectPort).toBe("function");
});

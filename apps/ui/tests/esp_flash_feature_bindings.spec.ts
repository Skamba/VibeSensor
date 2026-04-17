import { expect, test } from "@playwright/test";

import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import { signal } from "../src/app/ui_signals";
import type { EspFlashPanelActionHandlers } from "../src/app/views/esp_flash_panel";

test("bindHandlers uses panel action surfaces instead of raw DOM bindings", () => {
  const panel = {
    actions: signal<EspFlashPanelActionHandlers | null>(null),
    model: signal(null),
  };
  const feature = createEspFlashFeature({
    panel,
    ports: {
      activeSettingsTabId: signal("espFlashTab"),
      activeViewId: signal("settingsView"),
    },
    services: {
      t: (key) => key,
      requestConfirmation: async () => true,
      showError() {},
    },
  });

  expect(() => feature.bindHandlers()).not.toThrow();
  const handlers = panel.actions.value;
  expect(handlers).not.toBeNull();
  expect(typeof handlers?.onStart).toBe("function");
  expect(typeof handlers?.onCancel).toBe("function");
  expect(typeof handlers?.onRefreshPorts).toBe("function");
  expect(typeof handlers?.onSelectPort).toBe("function");
});

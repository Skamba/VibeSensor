import { expect, test } from "@playwright/test";

import { createUpdateFeature } from "../src/app/features/update_feature";
import { signal } from "../src/app/ui_signals";
import type { InternetPanelActionHandlers } from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
} from "../src/app/views/update_panel";

test("bindUpdateHandlers uses panel action surfaces instead of raw DOM listeners", () => {
  let updateHandlers: UpdatePanelActionHandlers | null = null;
  let internetHandlers: InternetPanelActionHandlers | null = null;

  const feature = createUpdateFeature({
    services: {
      t: (key) => key,
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
    ports: {
      activeSettingsTabId: signal("updateTab"),
      activeViewId: signal("settingsView"),
    },
    panels: {
      update: {
        bindActions(handlers: UpdatePanelActionHandlers) {
          updateHandlers = handlers;
        },
        bindModel() {},
      },
      internet: {
        bindActions(handlers: InternetPanelActionHandlers) {
          internetHandlers = handlers;
        },
        focusSsidInput() {},
        bindModel() {},
      },
    },
  });

  expect(() => feature.bindUpdateHandlers()).not.toThrow();
  expect(updateHandlers).not.toBeNull();
  expect(internetHandlers).not.toBeNull();
  expect(typeof internetHandlers?.onPasswordInput).toBe("function");
});

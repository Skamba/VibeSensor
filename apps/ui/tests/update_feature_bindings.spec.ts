import { expect, test } from "vitest";
import { createUpdateFeature } from "../src/app/features/update_feature";
import { signal } from "../src/app/ui_signals";
import type { InternetPanelActionHandlers } from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
} from "../src/app/views/update_panel";

test("bindUpdateHandlers uses panel action surfaces instead of raw DOM listeners", () => {
  const updatePanel = {
    actions: signal<UpdatePanelActionHandlers | null>(null),
    model: signal(null),
  };
  const internetPanel = {
    actions: signal<InternetPanelActionHandlers | null>(null),
    model: signal(null),
    focusSsidInput() {},
  };

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
      update: updatePanel,
      internet: internetPanel,
    },
  });

  expect(() => feature.bindUpdateHandlers()).not.toThrow();
  const updateHandlers = updatePanel.actions.value;
  const internetHandlers = internetPanel.actions.value;
  expect(updateHandlers).not.toBeNull();
  expect(internetHandlers).not.toBeNull();
  expect(typeof internetHandlers?.onPasswordInput).toBe("function");
});

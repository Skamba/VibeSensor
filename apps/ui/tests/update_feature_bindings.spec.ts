import { expect, test } from "@playwright/test";

import { createUpdateFeature } from "../src/app/features/update_feature";
import { signal } from "../src/app/ui_signals";
import type {
  InternetPanelActionHandlers,
  InternetPanelRenderModel,
} from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
  UpdatePanelRenderModel,
} from "../src/app/views/update_panel";

test("bindUpdateHandlers uses panel action surfaces instead of raw DOM listeners", () => {
  let updateHandlers: UpdatePanelActionHandlers | null = null;
  let internetHandlers: InternetPanelActionHandlers | null = null;

  const feature = createUpdateFeature({
    services: {
      t: (key) => key,
      showError: () => undefined,
    },
    ports: {
      getActiveSettingsTabId: () => "updateTab",
      activeViewId: signal("settingsView"),
      subscribeSettingsTabChanges: () => () => undefined,
    },
    panels: {
      update: {
        bindActions(handlers: UpdatePanelActionHandlers) {
          updateHandlers = handlers;
        },
        setModel(_model: UpdatePanelRenderModel) {},
      },
      internet: {
        bindActions(handlers: InternetPanelActionHandlers) {
          internetHandlers = handlers;
        },
        focusSsidInput() {},
        setModel(_model: InternetPanelRenderModel) {},
      },
    },
  });

  expect(() => feature.bindUpdateHandlers()).not.toThrow();
  expect(updateHandlers).not.toBeNull();
  expect(internetHandlers).not.toBeNull();
  expect(typeof internetHandlers?.onPasswordInput).toBe("function");
});

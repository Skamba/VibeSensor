import { expect, test } from "@playwright/test";

import { createUpdateFeature } from "../src/app/features/update_feature";
import type {
  InternetPanelActionHandlers,
  InternetPanelDom,
  InternetPanelRenderModel,
} from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
  UpdatePanelDom,
  UpdatePanelRenderModel,
} from "../src/app/views/update_panel";

function createInputStub(value = "", type = "text") {
  return {
    checked: false,
    disabled: false,
    type,
    value,
  } as HTMLInputElement;
}

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
      getActiveViewId: () => "settingsView",
      subscribePrimaryViewChanges: () => () => undefined,
      subscribeSettingsTabChanges: () => () => undefined,
    },
    panels: {
      update: {
        dom: {
          updateOverviewPanel: null,
          updateStartBtn: {} as HTMLButtonElement,
          updateCancelBtn: {} as HTMLButtonElement,
          updateStatusPanel: {} as HTMLElement,
        } as UpdatePanelDom,
        bindActions(handlers: UpdatePanelActionHandlers) {
          updateHandlers = handlers;
        },
        setModel(_model: UpdatePanelRenderModel) {},
      },
      internet: {
        dom: {
          internetStatusPanel: null,
          updateTransportOptions: null,
          updateTransportChoiceWifi: null,
          updateTransportChoiceUsb: null,
          updateWifiFields: null,
          updateReadinessSummary: null,
          updateDetailsCaption: null,
          updateTransportNote: null,
          updateTransportWifiRadio: createInputStub("", "radio"),
          updateTransportUsbRadio: createInputStub("", "radio"),
          updateUsbTransportSummary: null,
          updateSsidInput: createInputStub("MyWiFi"),
          updatePasswordInput: createInputStub("secret", "password"),
          updateTogglePasswordBtn: {} as HTMLButtonElement,
        } as InternetPanelDom,
        bindActions(handlers: InternetPanelActionHandlers) {
          internetHandlers = handlers;
        },
        setModel(_model: InternetPanelRenderModel) {},
      },
    },
  });

  expect(() => feature.bindUpdateHandlers()).not.toThrow();
  expect(updateHandlers).not.toBeNull();
  expect(internetHandlers).not.toBeNull();
  expect(typeof internetHandlers?.onPasswordInput).toBe("function");
});
